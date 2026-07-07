"""Tests for native HEC-RAS flow hydrograph optimization helpers."""

import logging
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import RasFlowOptimization

LOGGER_NAME = "ras_commander.RasFlowOptimization"


def _log_messages(caplog, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == level
    ]


class _DummyRas:
    project_folder = None

    def check_initialized(self):
        return None


def _write_plan(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "Plan Title=Base",
                "Program Version=6.40",
                "Short Identifier=Base",
                "Simulation Date=31dec1996,0000,05jan1997,0000",
                "Geom File=g01",
                "Flow File=u01",
                "Subcritical Flow",
                "CheckData=True",
                "Computation Interval=1MIN",
                "Output Interval=10MIN",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_unsteady(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "Flow Title=Flood",
                "Program Version=6.40",
                "Use Restart= 0 ",
                (
                    "Boundary Location=                ,                ,        ,"
                    "        ,                ,2DArea          ,                ,"
                    "Inflow                          ,"
                ),
                "Interval=1HOUR",
                "Flow Hydrograph= 0 ",
                "DSS File=.\\Flow_Data\\streamflow.dss",
                "DSS Path=/MERCED/FLOW/01DEC1996/15MIN/USGS/",
                "Use DSS=True",
                "Non-Newtonian Method= 0 ,",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_set_and_get_native_flow_optimization_settings(tmp_path):
    plan_path = tmp_path / "Project.p01"
    unsteady_path = tmp_path / "Project.u01"
    _write_plan(plan_path)
    _write_unsteady(unsteady_path)

    assert RasFlowOptimization.set_settings(
        plan_path,
        mode="stage",
        reference_location="LowPointOnRoad",
        target_value=3967.0,
        tolerance=0.1,
        initial_ratio=1.0,
        min_ratio=0.5,
        max_ratio=4.0,
        max_iterations=10,
        hydrographs=["Inflow"],
        ras_object=_DummyRas(),
    )

    content = plan_path.read_text(encoding="utf-8")
    assert "Flow Ratio Target=3967\n" in content
    assert "Flow Ratio Reference=Ref Point: LowPointOnRoad\n" in content
    assert "Flow Ratio User Selected Hydrographs=-1\n" in content
    assert "Flow Ratio Optimization Hydrograph=BCLine: Inflow\n" in content
    assert content.index("Flow Ratio Target=") < content.index("Computation Interval=")

    settings = RasFlowOptimization.get_settings(plan_path, ras_object=_DummyRas())
    assert settings["enabled"] is True
    assert settings["mode"] == "stage"
    assert settings["reference_location"] == "LowPointOnRoad"
    assert settings["target_value"] == 3967.0
    assert settings["max_iterations"] == 10
    assert settings["hydrographs"] == ["BCLine: Inflow"]

    unsteady_content = unsteady_path.read_text(encoding="utf-8")
    assert "Observed Time Series=Stage|TS Name=Ref Point: LowPointOnRoad\n" in unsteady_content
    assert "Observed Time Series=Stage|TS Constant Value=3967\n" in unsteady_content


def test_set_settings_success_logs_single_public_info(tmp_path, caplog):
    plan_path = tmp_path / "Project.p01"
    unsteady_path = tmp_path / "Project.u01"
    _write_plan(plan_path)
    _write_unsteady(unsteady_path)
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    RasFlowOptimization.set_settings(
        plan_path,
        mode="stage",
        reference_location="LowPointOnRoad",
        target_value=3967.0,
        hydrographs=["Inflow"],
        ras_object=_DummyRas(),
    )

    info_messages = _log_messages(caplog, logging.INFO)
    warning_messages = _log_messages(caplog, logging.WARNING)
    debug_messages = _log_messages(caplog, logging.DEBUG)

    assert info_messages == ["Updated flow optimization settings in Project.p01"]
    assert warning_messages == []
    assert all(str(tmp_path) not in message for message in info_messages)
    assert "Updated observed Stage target in Project.u01" in debug_messages


def test_list_flow_hydrographs_from_plan_unsteady_file(tmp_path):
    plan_path = tmp_path / "Project.p01"
    unsteady_path = tmp_path / "Project.u01"
    _write_plan(plan_path)
    _write_unsteady(unsteady_path)

    df = RasFlowOptimization.list_flow_hydrographs(
        plan_path,
        ras_object=_DummyRas(),
    )

    assert len(df) == 1
    assert df.loc[0, "bc_type"] == "Flow Hydrograph"
    assert df.loc[0, "flow_area"] == "2DArea"
    assert df.loc[0, "bc_line"] == "Inflow"
    assert df.loc[0, "optimization_hydrograph"] == "BCLine: Inflow"


def test_list_flow_hydrographs_logs_count_at_debug_only(tmp_path, caplog):
    plan_path = tmp_path / "Project.p01"
    unsteady_path = tmp_path / "Project.u01"
    _write_plan(plan_path)
    _write_unsteady(unsteady_path)
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    RasFlowOptimization.list_flow_hydrographs(plan_path, ras_object=_DummyRas())

    assert "Found 1 flow hydrograph boundary rows" in _log_messages(caplog, logging.DEBUG)
    assert "Found 1 flow hydrograph boundary rows" not in _log_messages(caplog, logging.INFO)


def test_list_flow_hydrographs_missing_unsteady_reports_expected_path(tmp_path):
    plan_path = tmp_path / "Project.p01"
    _write_plan(plan_path)
    expected_unsteady = tmp_path / "Project.u01"

    with pytest.raises(FileNotFoundError) as excinfo:
        RasFlowOptimization.list_flow_hydrographs(plan_path, ras_object=_DummyRas())

    message = str(excinfo.value)
    assert "Plan references Flow File=u01" in message
    assert str(expected_unsteady) in message


def test_observed_target_update_preserves_other_observed_series(tmp_path):
    plan_path = tmp_path / "Project.p01"
    unsteady_path = tmp_path / "Project.u01"
    _write_plan(plan_path)
    _write_unsteady(unsteady_path)
    content = unsteady_path.read_text(encoding="utf-8")
    content = content.replace(
        "Non-Newtonian Method= 0 ,\n",
        (
            "Observed Time Series=Stage|TS Name=Ref Point: LowPointOnRoad\n"
            "Observed Time Series=Stage|TS Used=-1\n"
            "Observed Time Series=Stage|TS Source=Constant\n"
            "Observed Time Series=Stage|TS Constant Value=3900\n"
            "Observed Time Series=Stage|TS Name=Ref Point: PreserveMe\n"
            "Observed Time Series=Stage|TS Used=-1\n"
            "Observed Time Series=Stage|TS Source=Constant\n"
            "Observed Time Series=Stage|TS Constant Value=4000\n"
            "Non-Newtonian Method= 0 ,\n"
        ),
    )
    unsteady_path.write_text(content, encoding="utf-8")

    RasFlowOptimization.set_settings(
        plan_path,
        mode="stage",
        reference_location="LowPointOnRoad",
        target_value=3967.0,
        hydrographs=["Inflow"],
        ras_object=_DummyRas(),
    )

    unsteady_content = unsteady_path.read_text(encoding="utf-8")
    assert "Observed Time Series=Stage|TS Constant Value=3967\n" in unsteady_content
    assert "Observed Time Series=Stage|TS Name=Ref Point: PreserveMe\n" in unsteady_content
    assert "Observed Time Series=Stage|TS Constant Value=4000\n" in unsteady_content


def test_set_settings_missing_unsteady_warning_is_concise_debug_has_path(tmp_path, caplog):
    plan_path = tmp_path / "Project.p01"
    expected_unsteady = tmp_path / "Project.u01"
    _write_plan(plan_path)
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    RasFlowOptimization.set_settings(
        plan_path,
        mode="stage",
        reference_location="LowPointOnRoad",
        target_value=3967.0,
        hydrographs=["Inflow"],
        ras_object=_DummyRas(),
    )

    warning_messages = _log_messages(caplog, logging.WARNING)
    assert (
        "Skipped observed target time-series update for Project.p01 "
        "(Ref Point: LowPointOnRoad): unsteady flow file not found"
    ) in warning_messages
    assert all(str(tmp_path) not in message for message in warning_messages)
    assert (
        f"Observed target unsteady path candidate: {expected_unsteady}"
        in _log_messages(caplog, logging.DEBUG)
    )


def test_missing_plan_number_reports_project_context_candidate_and_available_plans(tmp_path):
    class FakeRasObject:
        project_name = "Project"
        project_folder = tmp_path
        plan_df = pd.DataFrame({
            "plan_number": ["01"],
            "full_path": [str(tmp_path / "Project.p01")],
        })

        def check_initialized(self):
            return None

        def get_plan_entries(self):
            return self.plan_df

    with pytest.raises(FileNotFoundError) as excinfo:
        RasFlowOptimization.get_settings("02", ras_object=FakeRasObject())

    message = str(excinfo.value)
    assert "Plan file not found: 02" in message
    assert f"Project: Project in {tmp_path}" in message
    assert f"Expected path: {tmp_path / 'Project.p02'}" in message
    assert "Available plans: 01" in message


def test_parse_compute_message_trial_summary():
    messages = """
Unsteady Input Summary:
Hydro Flow Optimization Stage, Target 3967.00 ft at LowPointOnRoad
Hydro Flow Optimization Trial # 1
Optimization trial # 1 Ratio 1.000 Difference 1.765 Target 3967.00 Computed 3968.76
Hydro Flow Optimization Trial # 2
Optimization trial # 2 Ratio 0.833 Difference 1.037 Target 3967.00 Computed 3968.04
Hydro Flow Optimization Trial # 3
Optimization trial # 3 Ratio 0.500 Difference -0.532 Target 3967.00 Computed 3966.47
Hydro Flow Optimization Trial # 4
Optimization trial # 4 Ratio 0.613 Difference 0.062 Target 3967.00 Computed 3967.06
Hydro Flow Optimization Converged Trial # 4 Ratio 0.613
"""

    df = RasFlowOptimization.parse_compute_messages(messages)

    assert df["trial"].tolist() == [1, 2, 3, 4]
    assert df.loc[0, "mode"] == "stage"
    assert df.loc[0, "units"] == "ft"
    assert df.loc[0, "reference_location"] == "LowPointOnRoad"
    assert np.isclose(df.loc[2, "difference"], -0.532)
    assert bool(df.loc[3, "converged"]) is True


def test_get_trial_results_reads_hdf_dataset(tmp_path):
    hdf_path = tmp_path / "Project.p01.hdf"
    dtype = np.dtype(
        [
            ("Trial", "<i4"),
            ("Ratio", "<f8"),
            ("Difference", "<f8"),
            ("Target", "<f8"),
            ("Computed", "<f8"),
        ]
    )
    data = np.array(
        [
            (1, 1.0, 1.765, 3967.0, 3968.765),
            (2, 0.833, 1.037, 3967.0, 3968.037),
        ],
        dtype=dtype,
    )
    with h5py.File(hdf_path, "w") as hdf_file:
        hdf_file.create_dataset(
            "Results/Unsteady/Flow Optimization/Trials",
            data=data,
        )

    df = RasFlowOptimization.get_trial_results(hdf_path, ras_object=_DummyRas())

    assert df["source"].unique().tolist() == ["hdf"]
    assert df["trial"].tolist() == [1, 2]
    assert np.isclose(df.loc[1, "ratio"], 0.833)
    assert df.loc[0, "source_dataset"] == "Results/Unsteady/Flow Optimization/Trials"


def test_get_trial_results_falls_back_to_compute_messages(tmp_path):
    plan_path = tmp_path / "Project.p01"
    _write_plan(plan_path)
    Path(str(plan_path) + ".computeMsgs.txt").write_text(
        (
            "Hydro Flow Optimization Flow, Target 5000 cfs at RefLine1\n"
            "Optimization trial # 1 Ratio 1.200 Difference -100 "
            "Target 5000 Computed 4900\n"
        ),
        encoding="utf-8",
    )

    df = RasFlowOptimization.get_trial_results(plan_path, ras_object=_DummyRas())

    assert len(df) == 1
    assert df.loc[0, "source"] == "compute_messages"
    assert df.loc[0, "mode"] == "flow"
    assert df.loc[0, "units"] == "cfs"
    assert df.loc[0, "computed"] == 4900.0


def test_compute_plan_and_get_trials_reads_dest_folder(monkeypatch, tmp_path):
    project_folder = tmp_path / "Project"
    project_folder.mkdir()
    ras_object = _DummyRas()
    ras_object.project_folder = project_folder
    ras_object.project_name = "Project"

    dest_folder = tmp_path / "Project Optimized"

    def fake_compute_plan(plan_number, ras_object=None, **kwargs):
        dest_folder.mkdir()
        plan_path = dest_folder / "Project.p01"
        _write_plan(plan_path)
        Path(str(plan_path) + ".computeMsgs.txt").write_text(
            (
                "Hydro Flow Optimization Stage, Target 3963.5 ft at Vantage\n"
                "Optimization trial # 1 Ratio 0.900 Difference 0.1 "
                "Target 3963.5 Computed 3963.6\n"
            ),
            encoding="utf-8",
        )
        return True

    from ras_commander import RasCmdr

    monkeypatch.setattr(RasCmdr, "compute_plan", fake_compute_plan)

    result = RasFlowOptimization.compute_plan_and_get_trials(
        "01",
        ras_object=ras_object,
        dest_folder=dest_folder,
    )

    assert result["compute_result"] is True
    assert result["trial_results"].loc[0, "ratio"] == 0.9
    assert result["trial_results"].loc[0, "source_path"] == str(
        dest_folder / "Project.p01"
    )
