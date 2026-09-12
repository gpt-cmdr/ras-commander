import importlib
import os
import time
from pathlib import Path

import pandas as pd
import pytest

from ras_commander.ComputeResults import ComputeParallelResult, ComputeResult


rascmdr_module = importlib.import_module("ras_commander.RasCmdr")
RasCmdr = rascmdr_module.RasCmdr


@pytest.fixture(autouse=True)
def _complete_destination_promotion_gate(monkeypatch):
    """Keep batch unit tests independent of ambient host processes."""
    monkeypatch.setattr(
        RasCmdr,
        "_destination_promotion_process_gate",
        staticmethod(lambda *_args, **_kwargs: (True, {})),
    )


class FakeRasProject:
    DEFAULT_PLAN_NUMBERS = ["01", "02", "03"]

    def __init__(self, project_folder=None, plan_numbers=None):
        self.project_name = "TestProject"
        self.ras_exe_path = Path("C:/HEC-RAS/6.6/Ras.exe")
        self._plan_numbers = list(plan_numbers or self.DEFAULT_PLAN_NUMBERS)
        self.raise_on_get_plan_entries = False
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
        if self.raise_on_get_plan_entries:
            raise FileNotFoundError(self.prj_file)
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
        hdf_paths = [
            str(self.project_folder / f"{self.project_name}.p{plan_number}.hdf")
            for plan_number in plan_numbers
        ]
        self.results_df = pd.DataFrame(
            {
                "plan_number": plan_numbers,
                "status": ["done"] * len(plan_numbers),
                "HDF_Results_Path": hdf_paths,
                "hdf_path": hdf_paths,
            }
        )

    def close(self):
        return None


def fake_init_ras_project(
    ras_project_folder,
    ras_version=None,
    ras_object=None,
    load_results_summary=True,
    hide_intro=False,
    **kwargs,
):
    # Mirror init_ras_project's signature. compute_parallel initializes worker
    # projects with hide_intro=True; a narrower signature makes every worker init
    # raise TypeError and silently fails the whole parallel run.
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


def test_compute_parallel_result_adds_detached_evidence_without_breaking_mapping():
    details = {"01": {"nested": {"value": 1}}}
    results_df = pd.DataFrame({"plan_number": ["01"]})

    result = ComputeParallelResult({"01": True}, results_df, details)
    legacy_positional = ComputeParallelResult({"02": False}, results_df)
    details["01"]["nested"]["value"] = 2

    assert result["01"] is True
    assert list(result.items()) == [("01", True)]
    assert bool(result) is True
    assert result.results_df is results_df
    assert result.execution_details_by_plan == {
        "01": {"nested": {"value": 1}}
    }
    assert legacy_positional.execution_details_by_plan == {}


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
        compute_ras = kwargs["ras_object"]
        (
            Path(compute_ras.project_folder)
            / f"{compute_ras.project_name}.p{plan_number}.hdf"
        ).write_text("computed\n", encoding="utf-8")
        return ComputeResult(
            success=True,
            execution_details={"plan_number": plan_number, "worker": True},
        )

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
    assert result.execution_details_by_plan == {
        "01": {"plan_number": "01", "worker": True},
        "02": {"plan_number": "02", "worker": True},
    }
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
        compute_ras = kwargs["ras_object"]
        (
            Path(compute_ras.project_folder)
            / f"{compute_ras.project_name}.p{plan_number}.hdf"
        ).write_text("computed\n", encoding="utf-8")
        return ComputeResult(
            success=True,
            execution_details={"plan_number": plan_number, "sequential": True},
        )

    monkeypatch.setattr(rascmdr_module, "RasPrj", FakeRasProject)
    monkeypatch.setattr(RasCmdr, "compute_plan", staticmethod(fake_compute_plan))

    result = RasCmdr.compute_test_mode(
        plan_number=[1, "2"],
        dest_folder_suffix="[Normalized]",
        ras_object=ras_object,
    )

    assert executed_plans == ["01", "02"]
    assert result.execution_results == {"01": True, "02": True}
    assert result.execution_details_by_plan == {
        "01": {"plan_number": "01", "sequential": True},
        "02": {"plan_number": "02", "sequential": True},
    }
    assert result.results_df["plan_number"].tolist() == ["01", "02"]


def test_compute_parallel_records_not_attempted_details_for_source_skip(
    monkeypatch,
    tmp_path,
):
    project_folder = tmp_path / "parallel-skip"
    project_folder.mkdir()
    (project_folder / "TestProject.prj").write_text(
        "Proj Title=TestProject\n",
        encoding="utf-8",
    )
    ras_object = FakeRasProject(
        project_folder=project_folder,
        plan_numbers=["01", "02"],
    )

    monkeypatch.setattr(
        RasCmdr,
        "_verify_result",
        staticmethod(lambda *_args, **_kwargs: True),
    )

    result = RasCmdr.compute_parallel(
        plan_number="01",
        ras_object=ras_object,
        skip_existing=True,
    )

    assert result.execution_results == {"01": True}
    assert result.execution_details_by_plan["01"] == {
        "execution_api": "ras_cmdr",
        "engine_kind": "executable",
        "selected_result_format": "hdf",
        "calculation_attempted": False,
        "solver_quiescence_confirmed": None,
        "result_artifacts_finalized": False,
        "actual_engine_provenance_confirmed": False,
        "selected_executable_path": None,
        "selected_executable_sha256": None,
        "launcher_pid": None,
        "launcher_create_time": None,
    }


def test_compute_test_mode_preserves_structured_failure_details(
    monkeypatch,
    tmp_path,
):
    project_folder = tmp_path / "test-mode-failure"
    project_folder.mkdir()
    (project_folder / "TestProject.prj").write_text(
        "Proj Title=TestProject\n",
        encoding="utf-8",
    )
    ras_object = FakeRasProject(
        project_folder=project_folder,
        plan_numbers=["01"],
    )

    monkeypatch.setattr(rascmdr_module, "RasPrj", FakeRasProject)
    monkeypatch.setattr(
        RasCmdr,
        "compute_plan",
        staticmethod(
            lambda *_args, **_kwargs: ComputeResult(
                success=False,
                execution_details={
                    "calculation_attempted": True,
                    "failure_stage": "solver",
                },
            )
        ),
    )

    result = RasCmdr.compute_test_mode(
        plan_number="01",
        dest_folder_suffix="[Failure Evidence]",
        ras_object=ras_object,
    )

    assert result.execution_results == {"01": False}
    assert result.execution_details_by_plan == {
        "01": {
            "calculation_attempted": True,
            "failure_stage": "solver",
        }
    }


def test_compute_parallel_does_not_promote_copied_selected_result(
    monkeypatch,
    tmp_path,
) -> None:
    project_folder = tmp_path / "parallel-stale-result"
    project_folder.mkdir()
    _seed_parallel_project(project_folder)
    ras_object = FakeRasProject(
        project_folder=project_folder,
        plan_numbers=["01"],
    )
    original_hdf = project_folder / "TestProject.p01.hdf"

    monkeypatch.setattr(rascmdr_module, "RasPrj", FakeRasProject)
    monkeypatch.setattr(rascmdr_module, "init_ras_project", fake_init_ras_project)
    monkeypatch.setattr(rascmdr_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        RasCmdr,
        "compute_plan",
        staticmethod(lambda *_args, **_kwargs: ComputeResult(success=True)),
    )

    result = RasCmdr.compute_parallel(
        plan_number="01",
        max_workers=1,
        ras_object=ras_object,
    )

    assert result.execution_results == {"01": False}
    assert original_hdf.read_text(encoding="utf-8") == "stale hdf 01\n"
    retained_worker = project_folder.parent / (
        f"{project_folder.name} [Worker 1]"
    )
    details = result.execution_details_by_plan["01"]
    assert details["failure_stage"] == (
        "destination_promotion_missing_result"
    )
    assert "TestProject.p01.hdf" in details["failure_detail"]
    assert details["retained_worker_folder"] == str(retained_worker)
    assert details["promotion_failure"][
        "partial_promotion_possible"
    ] is False
    assert retained_worker.is_dir()


def test_compute_test_mode_does_not_promote_copied_selected_result(
    monkeypatch,
    tmp_path,
) -> None:
    project_folder = tmp_path / "test-mode-stale-result"
    project_folder.mkdir()
    _seed_parallel_project(project_folder)
    ras_object = FakeRasProject(
        project_folder=project_folder,
        plan_numbers=["01"],
    )
    original_hdf = project_folder / "TestProject.p01.hdf"

    monkeypatch.setattr(rascmdr_module, "RasPrj", FakeRasProject)
    monkeypatch.setattr(
        RasCmdr,
        "compute_plan",
        staticmethod(lambda *_args, **_kwargs: ComputeResult(success=True)),
    )

    result = RasCmdr.compute_test_mode(
        plan_number="01",
        dest_folder_suffix="[Stale Result]",
        ras_object=ras_object,
    )

    assert result.execution_results == {"01": False}
    assert original_hdf.read_text(encoding="utf-8") == "stale hdf 01\n"
    retained_test_folder = project_folder.parent / (
        f"{project_folder.name} [Stale Result]"
    )
    details = result.execution_details_by_plan["01"]
    assert details["failure_stage"] == (
        "destination_promotion_missing_result"
    )
    assert "TestProject.p01.hdf" in details["failure_detail"]
    assert details["retained_test_folder"] == str(retained_test_folder)
    assert details["promotion_failure"][
        "partial_promotion_possible"
    ] is False
    assert retained_test_folder.is_dir()


def test_compute_parallel_ancillary_copy_false_precedes_primary_and_retains(
    monkeypatch,
    tmp_path,
) -> None:
    project_folder = tmp_path / "parallel-copy-false"
    project_folder.mkdir()
    _seed_parallel_project(project_folder)
    ras_object = FakeRasProject(
        project_folder=project_folder,
        plan_numbers=["01"],
    )
    original_hdf = project_folder / "TestProject.p01.hdf"
    copy_calls = []

    def fake_compute_plan(plan_number, **kwargs):
        worker = Path(kwargs["ras_object"].project_folder)
        (worker / f"TestProject.p{plan_number}.hdf").write_text(
            "fresh parallel result\n",
            encoding="utf-8",
        )
        return ComputeResult(
            success=True,
            execution_details={"worker_plan": plan_number},
        )

    def refuse_first_copy(source_path, destination_path):
        copy_calls.append((Path(source_path), Path(destination_path)))
        return False

    monkeypatch.setattr(rascmdr_module, "RasPrj", FakeRasProject)
    monkeypatch.setattr(
        rascmdr_module,
        "init_ras_project",
        fake_init_ras_project,
    )
    monkeypatch.setattr(rascmdr_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(RasCmdr, "compute_plan", staticmethod(fake_compute_plan))
    monkeypatch.setattr(
        RasCmdr,
        "_copy_worker_artifact",
        staticmethod(refuse_first_copy),
    )
    monkeypatch.setattr(
        rascmdr_module,
        "finalize_plan_execution_artifacts",
        lambda *_args, **_kwargs: pytest.fail(
            "False copy receipt must prevent finalization"
        ),
    )

    result = RasCmdr.compute_parallel(
        plan_number="01",
        max_workers=1,
        ras_object=ras_object,
    )

    retained_worker = project_folder.parent / (
        f"{project_folder.name} [Worker 1]"
    )
    details = result.execution_details_by_plan["01"]
    assert result.execution_results == {"01": False}
    assert details["worker_plan"] == "01"
    assert details["failure_stage"] == "destination_promotion_staging"
    assert "returned False" in details["failure_detail"]
    assert details["retained_worker_folder"] == str(retained_worker)
    assert details["promotion_failure"]["source_path"].endswith(
        "TestProject.g01.hdf"
    )
    assert details["promotion_failure"][
        "partial_promotion_possible"
    ] is False
    assert [source.name for source, _ in copy_calls] == [
        "TestProject.g01.hdf"
    ]
    assert original_hdf.read_text(encoding="utf-8") == "stale hdf 01\n"
    assert (
        retained_worker / "TestProject.p01.hdf"
    ).read_text(encoding="utf-8") == "fresh parallel result\n"


def test_compute_test_mode_copy_false_retains_folder_and_skips_finalize(
    monkeypatch,
    tmp_path,
) -> None:
    project_folder = tmp_path / "test-mode-copy-false"
    project_folder.mkdir()
    _seed_parallel_project(project_folder)
    ras_object = FakeRasProject(
        project_folder=project_folder,
        plan_numbers=["01"],
    )
    original_hdf = project_folder / "TestProject.p01.hdf"

    def fake_compute_plan(plan_number, **kwargs):
        compute_folder = Path(kwargs["ras_object"].project_folder)
        (compute_folder / "TestProject.g01.hdf").unlink(missing_ok=True)
        (compute_folder / f"TestProject.p{plan_number}.hdf").write_text(
            "fresh test-mode result\n",
            encoding="utf-8",
        )
        return ComputeResult(
            success=True,
            execution_details={"test_plan": plan_number},
        )

    monkeypatch.setattr(rascmdr_module, "RasPrj", FakeRasProject)
    monkeypatch.setattr(RasCmdr, "compute_plan", staticmethod(fake_compute_plan))
    monkeypatch.setattr(
        RasCmdr,
        "_copy_worker_artifact",
        staticmethod(lambda *_args, **_kwargs: False),
    )
    monkeypatch.setattr(
        rascmdr_module,
        "finalize_plan_execution_artifacts",
        lambda *_args, **_kwargs: pytest.fail(
            "False copy receipt must prevent finalization"
        ),
    )

    result = RasCmdr.compute_test_mode(
        plan_number="01",
        dest_folder_suffix="[Copy False]",
        ras_object=ras_object,
    )

    retained_test_folder = project_folder.parent / (
        f"{project_folder.name} [Copy False]"
    )
    details = result.execution_details_by_plan["01"]
    assert result.execution_results == {"01": False}
    assert details["test_plan"] == "01"
    assert details["failure_stage"] == "destination_promotion_staging"
    assert "returned False" in details["failure_detail"]
    assert details["retained_test_folder"] == str(retained_test_folder)
    assert details["promotion_failure"]["source_path"].endswith(
        "TestProject.p01.hdf"
    )
    assert details["promotion_failure"][
        "partial_promotion_possible"
    ] is False
    assert original_hdf.read_text(encoding="utf-8") == "stale hdf 01\n"
    assert (
        retained_test_folder / "TestProject.p01.hdf"
    ).read_text(encoding="utf-8") == "fresh test-mode result\n"


def test_compute_parallel_finalization_permission_error_retains_worker(
    monkeypatch,
    tmp_path,
) -> None:
    project_folder = tmp_path / "parallel-finalize-error"
    project_folder.mkdir()
    _seed_parallel_project(project_folder)
    ras_object = FakeRasProject(
        project_folder=project_folder,
        plan_numbers=["01"],
    )
    original_hdf = project_folder / "TestProject.p01.hdf"

    def fake_compute_plan(plan_number, **kwargs):
        worker = Path(kwargs["ras_object"].project_folder)
        (worker / "TestProject.g01.hdf").unlink(missing_ok=True)
        (worker / f"TestProject.p{plan_number}.hdf").write_text(
            "fresh before failed finalization\n",
            encoding="utf-8",
        )
        return ComputeResult(success=True)

    monkeypatch.setattr(rascmdr_module, "RasPrj", FakeRasProject)
    monkeypatch.setattr(
        rascmdr_module,
        "init_ras_project",
        fake_init_ras_project,
    )
    monkeypatch.setattr(rascmdr_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(RasCmdr, "compute_plan", staticmethod(fake_compute_plan))
    monkeypatch.setattr(
        rascmdr_module,
        "finalize_plan_execution_artifacts",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PermissionError("finalization denied")
        ),
    )

    result = RasCmdr.compute_parallel(
        plan_number="01",
        max_workers=1,
        ras_object=ras_object,
    )

    retained_worker = project_folder.parent / (
        f"{project_folder.name} [Worker 1]"
    )
    details = result.execution_details_by_plan["01"]
    assert result.execution_results == {"01": False}
    assert details["failure_stage"] == (
        "destination_promotion_finalization"
    )
    assert details["failure_detail"] == (
        "PermissionError: finalization denied"
    )
    assert details["retained_worker_folder"] == str(retained_worker)
    assert details["promotion_failure"][
        "partial_promotion_possible"
    ] is False
    assert details["promotion_failure"]["rollback_confirmed"] is True
    assert details["promotion_failure"]["copied_destination_paths"]
    assert retained_worker.is_dir()
    assert original_hdf.read_text(encoding="utf-8") == (
        "stale hdf 01\n"
    )


def test_compute_test_mode_finalization_permission_error_retains_folder(
    monkeypatch,
    tmp_path,
) -> None:
    project_folder = tmp_path / "test-mode-finalize-error"
    project_folder.mkdir()
    _seed_parallel_project(project_folder)
    ras_object = FakeRasProject(
        project_folder=project_folder,
        plan_numbers=["01"],
    )
    original_hdf = project_folder / "TestProject.p01.hdf"

    def fake_compute_plan(plan_number, **kwargs):
        compute_folder = Path(kwargs["ras_object"].project_folder)
        (compute_folder / "TestProject.g01.hdf").unlink(missing_ok=True)
        (compute_folder / f"TestProject.p{plan_number}.hdf").write_text(
            "fresh before failed finalization\n",
            encoding="utf-8",
        )
        return ComputeResult(success=True)

    monkeypatch.setattr(rascmdr_module, "RasPrj", FakeRasProject)
    monkeypatch.setattr(RasCmdr, "compute_plan", staticmethod(fake_compute_plan))
    monkeypatch.setattr(
        rascmdr_module,
        "finalize_plan_execution_artifacts",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PermissionError("finalization denied")
        ),
    )

    result = RasCmdr.compute_test_mode(
        plan_number="01",
        dest_folder_suffix="[Finalize Error]",
        ras_object=ras_object,
    )

    retained_test_folder = project_folder.parent / (
        f"{project_folder.name} [Finalize Error]"
    )
    details = result.execution_details_by_plan["01"]
    assert result.execution_results == {"01": False}
    assert details["failure_stage"] == (
        "destination_promotion_finalization"
    )
    assert details["failure_detail"] == (
        "PermissionError: finalization denied"
    )
    assert details["retained_test_folder"] == str(retained_test_folder)
    assert details["promotion_failure"][
        "partial_promotion_possible"
    ] is False
    assert details["promotion_failure"]["rollback_confirmed"] is True
    assert details["promotion_failure"]["copied_destination_paths"] == [
        str(original_hdf)
    ]
    assert retained_test_folder.is_dir()
    assert original_hdf.read_text(encoding="utf-8") == (
        "stale hdf 01\n"
    )


@pytest.mark.parametrize(
    ("output_format", "primary_name"),
    [
        ("hdf", "TestProject.p01.hdf"),
        ("legacy", "TestProject.O01"),
    ],
)
def test_promotion_staging_failure_cannot_cross_attribute_new_messages(
    monkeypatch,
    tmp_path,
    output_format,
    primary_name,
) -> None:
    destination = tmp_path / f"destination-{output_format}"
    source = tmp_path / f"source-{output_format}"
    destination.mkdir()
    source.mkdir()
    (destination / "TestProject.prj").write_text(
        "Proj Title=TestProject\n",
        encoding="utf-8",
    )
    destination_primary = destination / primary_name
    destination_sidecar = destination / "TestProject.p01.computeMsgs.txt"
    source_primary = source / primary_name
    source_sidecar = source / "TestProject.p01.computeMsgs.txt"
    destination_primary.write_bytes(
        f"old {output_format} result without embedded messages".encode()
    )
    destination_sidecar.write_bytes(b"old-run messages")
    source_primary.write_bytes(f"fresh {output_format} result".encode())
    source_sidecar.write_bytes(b"fresh-run computation complete")
    old_primary = destination_primary.read_bytes()
    old_sidecar = destination_sidecar.read_bytes()
    original_copy = RasCmdr._copy_worker_artifact

    def fail_after_sidecar_staged(source_path, destination_path):
        if Path(source_path) == source_primary:
            return False
        return original_copy(Path(source_path), Path(destination_path))

    monkeypatch.setattr(
        RasCmdr,
        "_copy_worker_artifact",
        staticmethod(fail_after_sidecar_staged),
    )
    monkeypatch.setattr(
        rascmdr_module,
        "finalize_plan_execution_artifacts",
        lambda *_args, **_kwargs: pytest.fail(
            "A staging failure must not reach finalization"
        ),
    )

    succeeded, evidence = RasCmdr._publish_plan_artifacts_transaction(
        "01",
        source_primary=source_primary,
        source_sidecars=[source_sidecar],
        geometry_source=None,
        output_format=output_format,
        ras_object=FakeRasProject(destination, ["01"]),
        destination_folder=destination,
        project_name="TestProject",
    )

    assert succeeded is False
    assert evidence["failure_stage"] == "destination_promotion_staging"
    assert evidence["source_path"] == str(source_primary)
    assert evidence["rollback_attempted"] is False
    assert evidence["rollback_confirmed"] is True
    assert evidence["partial_promotion_possible"] is False
    assert evidence["retained_transaction_path"] is None
    assert destination_primary.read_bytes() == old_primary
    assert destination_sidecar.read_bytes() == old_sidecar
    assert not list(destination.glob(".rcp-*"))


def test_promotion_transaction_commits_one_same_run_artifact_set(tmp_path):
    destination = tmp_path / "destination-success"
    source = tmp_path / "source-success"
    destination.mkdir()
    source.mkdir()
    (destination / "TestProject.prj").write_text(
        "Proj Title=TestProject\n",
        encoding="utf-8",
    )
    destination_hdf = destination / "TestProject.p01.hdf"
    destination_legacy = destination / "TestProject.O01"
    destination_geometry = destination / "TestProject.g01.hdf"
    selected_sidecar = destination / "TestProject.p01.computeMsgs.txt"
    stale_sidecars = [
        destination / "TestProject.p01.comp_msgs.txt",
        destination / "TestProject.bco01",
    ]
    for path, contents in [
        (destination_hdf, b"old hdf"),
        (destination_legacy, b"old legacy"),
        (destination_geometry, b"old geometry"),
        (selected_sidecar, b"old selected messages"),
        (stale_sidecars[0], b"old alternate messages"),
        (stale_sidecars[1], b"old bco messages"),
    ]:
        path.write_bytes(contents)
    source_hdf = source / destination_hdf.name
    source_sidecar = source / selected_sidecar.name
    source_geometry = source / destination_geometry.name
    source_hdf.write_bytes(b"fresh hdf")
    source_sidecar.write_bytes(b"fresh same-run messages")
    source_geometry.write_bytes(b"fresh geometry")

    succeeded, evidence = RasCmdr._publish_plan_artifacts_transaction(
        "01",
        source_primary=source_hdf,
        source_sidecars=[source_sidecar],
        geometry_source=source_geometry,
        output_format="hdf",
        ras_object=FakeRasProject(destination, ["01"]),
        destination_folder=destination,
        project_name="TestProject",
    )

    assert succeeded is True
    assert evidence["failure_stage"] is None
    assert evidence["retained_transaction_path"] is None
    assert destination_hdf.read_bytes() == b"fresh hdf"
    assert selected_sidecar.read_bytes() == b"fresh same-run messages"
    assert destination_geometry.read_bytes() == b"fresh geometry"
    assert not destination_legacy.exists()
    assert all(not path.exists() for path in stale_sidecars)
    assert not list(destination.glob(".rcp-*"))


def test_promotion_transaction_restores_exact_prior_state_on_finalize_failure(
    monkeypatch,
    tmp_path,
) -> None:
    destination = tmp_path / "destination-rollback"
    source = tmp_path / "source-rollback"
    destination.mkdir()
    source.mkdir()
    (destination / "TestProject.prj").write_text(
        "Proj Title=TestProject\n",
        encoding="utf-8",
    )
    prior_contents = {
        destination / "TestProject.p01.hdf": b"old hdf",
        destination / "TestProject.O01": b"old legacy",
        destination / "TestProject.p01.computeMsgs.txt": b"old messages",
        destination / "TestProject.p01.comp_msgs.txt": b"old alternate",
        destination / "TestProject.bco01": b"old bco",
        destination / "TestProject.g01.hdf": b"old geometry",
    }
    for path, contents in prior_contents.items():
        path.write_bytes(contents)
    source_hdf = source / "TestProject.p01.hdf"
    source_sidecar = source / "TestProject.p01.computeMsgs.txt"
    source_geometry = source / "TestProject.g01.hdf"
    source_hdf.write_bytes(b"fresh hdf")
    source_sidecar.write_bytes(b"fresh messages")
    source_geometry.write_bytes(b"fresh geometry")
    monkeypatch.setattr(
        rascmdr_module,
        "finalize_plan_execution_artifacts",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PermissionError("finalization denied")
        ),
    )

    succeeded, evidence = RasCmdr._publish_plan_artifacts_transaction(
        "01",
        source_primary=source_hdf,
        source_sidecars=[source_sidecar],
        geometry_source=source_geometry,
        output_format="hdf",
        ras_object=FakeRasProject(destination, ["01"]),
        destination_folder=destination,
        project_name="TestProject",
    )

    assert succeeded is False
    assert evidence["failure_stage"] == (
        "destination_promotion_finalization"
    )
    assert evidence["rollback_attempted"] is True
    assert evidence["rollback_confirmed"] is True
    assert evidence["partial_promotion_possible"] is False
    assert evidence["retained_transaction_path"] is None
    assert all(path.read_bytes() == contents for path, contents in prior_contents.items())
    assert not list(destination.glob(".rcp-*"))


def test_promotion_transaction_retains_backups_when_primary_restore_fails(
    monkeypatch,
    tmp_path,
) -> None:
    destination = tmp_path / "destination-rollback-failure"
    source = tmp_path / "source-rollback-failure"
    destination.mkdir()
    source.mkdir()
    (destination / "TestProject.prj").write_text(
        "Proj Title=TestProject\n",
        encoding="utf-8",
    )
    destination_hdf = destination / "TestProject.p01.hdf"
    destination_sidecar = destination / "TestProject.p01.computeMsgs.txt"
    destination_hdf.write_bytes(b"old hdf")
    destination_sidecar.write_bytes(b"old messages")
    source_hdf = source / destination_hdf.name
    source_sidecar = source / destination_sidecar.name
    source_hdf.write_bytes(b"fresh hdf")
    source_sidecar.write_bytes(b"fresh messages")
    real_replace = rascmdr_module.os.replace

    def refuse_primary_restore(source_path, destination_path):
        source_path = Path(source_path)
        destination_path = Path(destination_path)
        if (
            source_path.parent.name == "b"
            and destination_path == destination_hdf
        ):
            raise PermissionError("primary restore denied")
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(rascmdr_module.os, "replace", refuse_primary_restore)
    monkeypatch.setattr(
        rascmdr_module,
        "finalize_plan_execution_artifacts",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PermissionError("finalization denied")
        ),
    )

    succeeded, evidence = RasCmdr._publish_plan_artifacts_transaction(
        "01",
        source_primary=source_hdf,
        source_sidecars=[source_sidecar],
        geometry_source=None,
        output_format="hdf",
        ras_object=FakeRasProject(destination, ["01"]),
        destination_folder=destination,
        project_name="TestProject",
    )

    assert succeeded is False
    assert evidence["rollback_attempted"] is True
    assert evidence["rollback_confirmed"] is False
    assert evidence["partial_promotion_possible"] is True
    assert evidence["retained_transaction_path"] is not None
    assert Path(evidence["retained_transaction_path"]).is_dir()
    assert evidence["backup_paths_remaining"]
    assert not destination_hdf.exists()
    assert not destination_sidecar.exists()


def test_promotion_rollback_requarantines_first_primary_if_second_fails(
    monkeypatch,
    tmp_path,
) -> None:
    destination = tmp_path / "destination-mixed-rollback-failure"
    source = tmp_path / "source-mixed-rollback-failure"
    destination.mkdir()
    source.mkdir()
    (destination / "TestProject.prj").write_text(
        "Proj Title=TestProject\n",
        encoding="utf-8",
    )
    destination_hdf = destination / "TestProject.p01.hdf"
    destination_legacy = destination / "TestProject.O01"
    destination_sidecar = destination / "TestProject.p01.computeMsgs.txt"
    destination_hdf.write_bytes(b"old hdf")
    destination_legacy.write_bytes(b"old legacy")
    destination_sidecar.write_bytes(b"old messages")
    source_hdf = source / destination_hdf.name
    source_sidecar = source / destination_sidecar.name
    source_hdf.write_bytes(b"fresh hdf")
    source_sidecar.write_bytes(b"fresh messages")
    real_replace = rascmdr_module.os.replace

    def refuse_second_primary_restore(source_path, destination_path):
        source_path = Path(source_path)
        destination_path = Path(destination_path)
        if (
            source_path.parent.name == "b"
            and destination_path == destination_legacy
        ):
            raise PermissionError("legacy restore denied")
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(
        rascmdr_module.os,
        "replace",
        refuse_second_primary_restore,
    )
    monkeypatch.setattr(
        rascmdr_module,
        "finalize_plan_execution_artifacts",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PermissionError("finalization denied")
        ),
    )

    succeeded, evidence = RasCmdr._publish_plan_artifacts_transaction(
        "01",
        source_primary=source_hdf,
        source_sidecars=[source_sidecar],
        geometry_source=None,
        output_format="hdf",
        ras_object=FakeRasProject(destination, ["01"]),
        destination_folder=destination,
        project_name="TestProject",
    )

    assert succeeded is False
    assert evidence["rollback_confirmed"] is False
    assert evidence["partial_promotion_possible"] is True
    assert Path(evidence["retained_transaction_path"]).is_dir()
    assert not destination_hdf.exists()
    assert not destination_legacy.exists()
    assert not destination_sidecar.exists()
    backup_names = {
        Path(path).name for path in evidence["backup_paths_remaining"]
    }
    assert {
        "00-TestProject.p01.hdf",
        "01-TestProject.O01",
        "03-TestProject.p01.computeMsgs.txt",
    }.issubset(backup_names)


def test_compute_parallel_refuses_entire_promotion_when_destination_is_occupied(
    monkeypatch,
    tmp_path,
) -> None:
    project_folder = tmp_path / "parallel-occupied"
    project_folder.mkdir()
    _seed_parallel_project(project_folder)
    ras_object = FakeRasProject(
        project_folder=project_folder,
        plan_numbers=["01", "02"],
    )
    gate_calls = []

    def fake_compute_plan(plan_number, **kwargs):
        worker = Path(kwargs["ras_object"].project_folder)
        (worker / f"TestProject.p{plan_number}.hdf").write_text(
            f"fresh hdf {plan_number}\n",
            encoding="utf-8",
        )
        return ComputeResult(
            success=True,
            execution_details={"worker_plan": plan_number},
        )

    evidence = {
        "complete": True,
        "quiescence_confirmed": False,
        "blocked_plan_numbers": ["02"],
    }

    def occupied_gate(plan_numbers, **kwargs):
        gate_calls.append((list(plan_numbers), kwargs))
        return False, evidence

    monkeypatch.setattr(rascmdr_module, "RasPrj", FakeRasProject)
    monkeypatch.setattr(
        rascmdr_module,
        "init_ras_project",
        fake_init_ras_project,
    )
    monkeypatch.setattr(rascmdr_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(RasCmdr, "compute_plan", staticmethod(fake_compute_plan))
    monkeypatch.setattr(
        RasCmdr,
        "_destination_promotion_process_gate",
        staticmethod(occupied_gate),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_copy_worker_artifact",
        staticmethod(
            lambda *_args, **_kwargs: pytest.fail(
                "No artifact may be copied after the batch gate refuses promotion"
            )
        ),
    )

    result = RasCmdr.compute_parallel(
        plan_number=["01", "02"],
        max_workers=2,
        ras_object=ras_object,
    )

    assert result.execution_results == {"01": False, "02": False}
    assert gate_calls == [
        (
            ["01", "02"],
            {
                "project_folder": project_folder,
                "project_name": "TestProject",
            },
        )
    ]
    for plan_number in ("01", "02"):
        worker_number = 1 if plan_number == "01" else 2
        retained_worker = project_folder.parent / (
            f"{project_folder.name} [Worker {worker_number}]"
        )
        assert result.execution_details_by_plan[plan_number][
            "worker_plan"
        ] == plan_number
        assert result.execution_details_by_plan[plan_number][
            "failure_stage"
        ] == "destination_promotion_process_gate"
        assert result.execution_details_by_plan[plan_number][
            "destination_promotion_process_gate"
        ] == evidence
        assert result.execution_details_by_plan[plan_number][
            "retained_worker_folder"
        ] == str(retained_worker)
        assert retained_worker.is_dir()
        assert (
            retained_worker / f"TestProject.p{plan_number}.hdf"
        ).read_text(encoding="utf-8") == f"fresh hdf {plan_number}\n"
        assert (
            project_folder / f"TestProject.p{plan_number}.hdf"
        ).read_text(encoding="utf-8") == f"stale hdf {plan_number}\n"


def test_compute_test_mode_refuses_promotion_on_incomplete_destination_gate(
    monkeypatch,
    tmp_path,
) -> None:
    project_folder = tmp_path / "test-mode-indeterminate"
    project_folder.mkdir()
    _seed_parallel_project(project_folder)
    ras_object = FakeRasProject(
        project_folder=project_folder,
        plan_numbers=["01"],
    )
    gate_calls = []

    def fake_compute_plan(plan_number, **kwargs):
        worker = Path(kwargs["ras_object"].project_folder)
        if plan_number == "01":
            (worker / f"TestProject.p{plan_number}.hdf").write_text(
                "fresh hdf 01\n",
                encoding="utf-8",
            )
        return ComputeResult(
            success=plan_number == "01",
            execution_details={"sequential_plan": plan_number},
        )

    evidence = {
        "complete": False,
        "quiescence_confirmed": None,
        "query_errors": [{"operation": "query_cmdline"}],
    }

    def incomplete_gate(plan_numbers, **kwargs):
        gate_calls.append((list(plan_numbers), kwargs))
        return False, evidence

    monkeypatch.setattr(rascmdr_module, "RasPrj", FakeRasProject)
    monkeypatch.setattr(RasCmdr, "compute_plan", staticmethod(fake_compute_plan))
    monkeypatch.setattr(
        RasCmdr,
        "_destination_promotion_process_gate",
        staticmethod(incomplete_gate),
    )
    monkeypatch.setattr(
        RasCmdr,
        "_copy_worker_artifact",
        staticmethod(
            lambda *_args, **_kwargs: pytest.fail(
                "No artifact may be copied after an indeterminate batch gate"
            )
        ),
    )

    result = RasCmdr.compute_test_mode(
        plan_number=["01", "02"],
        dest_folder_suffix="[Indeterminate]",
        ras_object=ras_object,
    )

    assert result.execution_results == {"01": False, "02": False}
    assert gate_calls == [
        (
            ["01"],
            {
                "project_folder": project_folder,
                "project_name": "TestProject",
            },
        )
    ]
    assert result.execution_details_by_plan["01"][
        "sequential_plan"
    ] == "01"
    assert result.execution_details_by_plan["01"][
        "failure_stage"
    ] == "destination_promotion_process_gate"
    assert result.execution_details_by_plan["01"][
        "destination_promotion_process_gate"
    ] == evidence
    retained_test_folder = project_folder.parent / (
        f"{project_folder.name} [Indeterminate]"
    )
    assert result.execution_details_by_plan["01"][
        "retained_test_folder"
    ] == str(retained_test_folder)
    assert result.execution_details_by_plan["02"] == {
        "sequential_plan": "02",
        "retained_test_folder": str(retained_test_folder),
    }
    assert retained_test_folder.is_dir()
    assert (
        retained_test_folder / "TestProject.p01.hdf"
    ).read_text(encoding="utf-8") == "fresh hdf 01\n"
    assert (
        project_folder / "TestProject.p01.hdf"
    ).read_text(encoding="utf-8") == "stale hdf 01\n"


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
    # Worker-local plan edits are not result evidence and are not promoted.
    assert (project_folder / "TestProject.p01").read_text(encoding="utf-8") == (
        "stale plan 01\n"
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
        "stale plan 01\n"
    )
    assert (dest_folder / "TestProject.g01.hdf").read_text(encoding="utf-8") == (
        "fresh geometry\n"
    )
    assert (dest_folder / "TestProject.p02.hdf").read_text(encoding="utf-8") == (
        "fresh hdf 02\n"
    )


def test_compute_parallel_uses_cached_plan_entries_when_prj_refresh_fails(
    monkeypatch, tmp_path
):
    project_folder = tmp_path / "parallel-project"
    project_folder.mkdir()
    _seed_parallel_project(project_folder)
    ras_object = FakeRasProject(
        project_folder=project_folder,
        plan_numbers=["01"],
    )
    ras_object.raise_on_get_plan_entries = True

    def fake_compute_plan(plan_number, **kwargs):
        worker_folder = Path(kwargs["ras_object"].project_folder)
        (worker_folder / f"TestProject.p{plan_number}.hdf").write_text(
            f"fresh hdf {plan_number}\n",
            encoding="utf-8",
        )
        return ComputeResult(success=True)

    monkeypatch.setattr(rascmdr_module, "RasPrj", FakeRasProject)
    monkeypatch.setattr(rascmdr_module, "init_ras_project", fake_init_ras_project)
    monkeypatch.setattr(rascmdr_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(RasCmdr, "compute_plan", staticmethod(fake_compute_plan))

    result = RasCmdr.compute_parallel(
        plan_number=["01"],
        max_workers=1,
        ras_object=ras_object,
    )

    assert result.execution_results == {"01": True}
    assert result.results_df["plan_number"].tolist() == ["01"]
    assert result.results_df["hdf_path"].tolist() == [
        str(project_folder / "TestProject.p01.hdf")
    ]


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
