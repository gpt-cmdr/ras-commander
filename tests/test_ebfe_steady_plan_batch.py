from pathlib import Path
import threading
from types import SimpleNamespace

import pandas as pd
import pytest

from ras_commander.sources import RasEbfeModels
from ras_commander.sources.base import ModelType
from scripts.ebfe_steady_plan_batch import (
    apply_study_defaults,
    expected_profiles_for_project,
    expected_hdf_path,
    resolve_study_paths,
    run_plan,
    selected_plans,
    stage_project,
    steady_profile_count,
)


def test_resolve_study_paths_uses_huc_workspace_contract(tmp_path):
    source, run_root, reports = resolve_study_paths(
        "12090301",
        tmp_path,
        "20260908_120000",
        None,
        None,
        False,
    )

    workspace = tmp_path / "12090301"
    assert source == (
        workspace
        / "organized"
        / "LowerColoradoCummins_12090301"
        / "RAS Model"
    )
    assert run_root == workspace / "runs" / "20260908_120000"
    assert reports == (
        workspace / "reports" / "steady_plan_validation" / "20260908_120000"
    )


def test_stage_project_copies_assets_but_not_nested_projects(tmp_path):
    source = tmp_path / "source" / "PARENT"
    source.mkdir(parents=True)
    prj = source / "PARENT.prj"
    prj.write_text("Proj Title=Parent\n", encoding="utf-8")
    (source / "PARENT.p01").write_text("Plan Title=Parent\n", encoding="utf-8")
    data = source / "data"
    data.mkdir()
    (data / "notes.txt").write_text("keep", encoding="utf-8")
    child = source / "CHILD"
    child.mkdir()
    (child / "CHILD.prj").write_text("Proj Title=Child\n", encoding="utf-8")

    staged = stage_project(
        {
            "folder": source,
            "project_name": "PARENT",
            "prj_file": prj,
            "plan_count": 1,
            "plan_numbers": ["01"],
        },
        1,
        tmp_path / "runs",
    )

    destination = Path(staged["folder"])
    assert (destination / "PARENT.prj").is_file()
    assert (destination / "data" / "notes.txt").is_file()
    assert not (destination / "CHILD").exists()
    assert staged["source_folder"] == source


def test_plan_paths_and_profile_count_come_from_plan_df(tmp_path):
    plan_path = tmp_path / "Model.p01"
    flow_path = tmp_path / "Model.f01"
    flow_path.write_text("Flow Title=Multiple\nNumber of Profiles= 7\n", encoding="utf-8")
    ras_obj = SimpleNamespace(
        plan_df=pd.DataFrame(
            [
                {
                    "plan_number": "01",
                    "full_path": str(plan_path),
                    "HDF_Results_Path": None,
                    "Flow Path": str(flow_path),
                }
            ]
        )
    )

    assert expected_hdf_path(ras_obj, "01") == Path(f"{plan_path}.hdf")
    assert steady_profile_count(ras_obj, "01") == 7


def test_selected_plans_preserves_legacy_all_plans_default():
    ras_obj = SimpleNamespace(
        plan_df=pd.DataFrame([{"plan_number": "01"}, {"plan_number": "02"}])
    )

    assert selected_plans(ras_obj, None) == ["01", "02"]
    assert selected_plans(ras_obj, "02") == ["02"]


def test_study_defaults_are_catalogued_and_reject_nonsteady_studies():
    args = SimpleNamespace(
        plan=None,
        expected_profiles=None,
        include_nested_projects=False,
        plan_timeout_seconds=None,
    )
    metadata = RasEbfeModels.get_model_metadata("12090301")

    assert apply_study_defaults(args, metadata) is True
    assert args.plan == "01"
    assert args.expected_profiles == 7
    assert args.expected_profile_exceptions == {
        "Walnut Creek-Colorado River/WALNUT 0329": 6,
    }
    assert args.plan_timeout_seconds == 600

    metadata.model_type = ModelType.UNSTEADY_2D
    with pytest.raises(ValueError, match="only STEADY_1D"):
        apply_study_defaults(args, metadata)


def test_catalogued_profile_exception_uses_stable_project_key(tmp_path):
    args = SimpleNamespace(
        expected_profiles=7,
        expected_profile_exceptions={
            "Walnut Creek-Colorado River/WALNUT 0329": 6,
        },
    )
    project_info = {
        "folder": tmp_path / "run-copy",
        "source_folder": (
            tmp_path
            / "Walnut Creek-Colorado River"
            / "WALNUT 0329"
        ),
    }

    assert expected_profiles_for_project(args, project_info) == 6

    project_info["source_folder"] = (
        tmp_path / "Walnut Creek-Colorado River" / "WALNUT 0330"
    )
    assert expected_profiles_for_project(args, project_info) == 7


def test_run_plan_cancels_owned_process_after_study_timeout(
    tmp_path,
    monkeypatch,
):
    plan_path = tmp_path / "Model.p01"
    flow_path = tmp_path / "Model.f01"
    plan_path.write_text("Plan Title=Test\n", encoding="utf-8")
    flow_path.write_text(
        "Flow Title=Test\nNumber of Profiles= 7\n",
        encoding="utf-8",
    )
    ras_obj = SimpleNamespace(
        plan_df=pd.DataFrame(
            [
                {
                    "plan_number": "01",
                    "full_path": str(plan_path),
                    "HDF_Results_Path": None,
                    "Flow Path": str(flow_path),
                }
            ]
        )
    )
    cancelled = threading.Event()

    def fake_compute_plan(*args, **kwargs):
        assert cancelled.wait(timeout=1.0)
        return True

    def fake_cancel_plan(*args, **kwargs):
        cancelled.set()
        return True

    monkeypatch.setattr(
        "scripts.ebfe_steady_plan_batch.RasPlan.update_run_flags",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "scripts.ebfe_steady_plan_batch.RasCmdr.compute_plan",
        fake_compute_plan,
    )
    monkeypatch.setattr(
        "scripts.ebfe_steady_plan_batch.RasCmdr.cancel_plan",
        fake_cancel_plan,
    )
    args = SimpleNamespace(
        expected_profiles=7,
        clear_geompre=False,
        force_geompre=False,
        no_force_rerun=False,
        num_cores=2,
        skip_existing=False,
        plan_timeout_seconds=0.01,
    )

    record = run_plan(ras_obj, "01", tmp_path / "logs", args)

    assert record["status"] == "failed"
    assert record["timed_out"] is True
    assert record["timeout_cancelled"] is True
    assert "exceeded" in record["error"]
