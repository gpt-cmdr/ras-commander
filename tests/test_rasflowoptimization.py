"""Tests for native HEC-RAS flow hydrograph optimization helpers."""

from pathlib import Path

import h5py
import numpy as np

from ras_commander import RasFlowOptimization


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
