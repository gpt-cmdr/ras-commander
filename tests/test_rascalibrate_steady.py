from pathlib import Path
import importlib
import logging

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import (
    CalibrationPoint,
    RasCalibrate,
    extract_modeled,
    extract_steady_profile_modeled,
    extract_steady_profile_observations,
    make_steady_profile_calibration_points,
)


def _write_steady_hdf(path: Path) -> Path:
    base_path = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles"
    xs_path = f"{base_path}/Cross Sections"
    geom_info_path = "Results/Steady/Output/Geometry Info"

    with h5py.File(path, "w") as hdf:
        profile_group = hdf.require_group(base_path)
        profile_group.create_dataset(
            "Profile Names",
            data=np.array([b"PF 1", b"PF 2"]),
        )

        xs_group = hdf.require_group(xs_path)
        xs_group.create_dataset(
            "Water Surface",
            data=np.array(
                [
                    [101.1, 102.2, 103.3],
                    [201.1, 202.2, 203.3],
                ],
                dtype=float,
            ),
        )

        attrs_dtype = np.dtype(
            [
                ("River", "S32"),
                ("Reach", "S32"),
                ("Station", "S16"),
            ]
        )
        attrs = np.array(
            [
                (b"River A", b"Reach 1", b"100"),
                (b"River A", b"Reach 1", b"200"),
                (b"River A", b"Reach 1", b"300.05"),
            ],
            dtype=attrs_dtype,
        )
        hdf.require_group(geom_info_path).create_dataset(
            "Cross Section Attributes",
            data=attrs,
        )

    return path


@pytest.fixture()
def steady_hdf(tmp_path: Path) -> Path:
    return _write_steady_hdf(tmp_path / "steady.p01.hdf")


def test_extract_steady_profile_modeled_exact_station(steady_hdf: Path) -> None:
    point = CalibrationPoint(
        name="PF1 RS200",
        variable="wse",
        extraction_method="steady_profile",
        observed=102.0,
        river="River A",
        reach="Reach 1",
        station="200",
        profile_name="PF 1",
    )

    assert extract_steady_profile_modeled(point, steady_hdf) == pytest.approx(102.2)
    assert extract_modeled(point, steady_hdf) == pytest.approx(102.2)


def test_extract_steady_profile_modeled_numeric_station_match(
    steady_hdf: Path,
) -> None:
    point = CalibrationPoint(
        name="PF2 RS200 numeric",
        variable="wse",
        extraction_method="steady_profile",
        observed=202.0,
        river="River A",
        reach="Reach 1",
        station="200.0",
        profile_name="PF 2",
    )

    assert extract_steady_profile_modeled(point, steady_hdf) == pytest.approx(202.2)


def test_extract_steady_profile_modeled_station_tolerance(
    steady_hdf: Path,
) -> None:
    point = CalibrationPoint(
        name="PF1 RS300 tolerance",
        variable="wse",
        extraction_method="steady_profile",
        observed=103.0,
        river="River A",
        reach="Reach 1",
        station="300.0",
        profile_name="PF 1",
        station_tolerance=0.1,
    )

    assert extract_steady_profile_modeled(point, steady_hdf) == pytest.approx(103.3)


def test_extract_steady_profile_modeled_station_mismatch_is_clear(
    steady_hdf: Path,
) -> None:
    point = CalibrationPoint(
        name="missing station",
        variable="wse",
        extraction_method="steady_profile",
        observed=99.0,
        river="River A",
        reach="Reach 1",
        station="999",
        profile_name="PF 1",
    )

    with pytest.raises(ValueError, match="No steady-profile row matched station"):
        extract_steady_profile_modeled(point, steady_hdf)


def test_extract_observations_profile_filter_and_make_points(
    steady_hdf: Path,
) -> None:
    all_observations = extract_steady_profile_observations(steady_hdf)
    all_points = make_steady_profile_calibration_points(all_observations)

    assert len(all_points) == 6
    assert {point.profile_name for point in all_points} == {"PF 1", "PF 2"}

    observations = extract_steady_profile_observations(
        steady_hdf,
        profiles=["PF 2"],
    )

    assert observations["profile"].unique().tolist() == ["PF 2"]
    assert observations["observed"].tolist() == pytest.approx(
        [201.1, 202.2, 203.3]
    )

    points = make_steady_profile_calibration_points(
        observations,
        station_tolerance=0.05,
    )

    assert len(points) == 3
    assert {point.extraction_method for point in points} == {"steady_profile"}
    assert {point.profile_name for point in points} == {"PF 2"}
    assert points[1].observed == pytest.approx(202.2)


def test_grid_search_passes_remote_and_geometry_controls(monkeypatch) -> None:
    rascal_module = importlib.import_module("ras_commander.RasCalibrate")
    calls = {}

    def fake_define_parameters(parameters):
        calls["parameters"] = parameters
        return pd.DataFrame({"n_main": [0.0315]})

    def fake_generate_plans(
        template_plan,
        parameters_df,
        apply_fn,
        suffix,
        max_plans_per_batch,
        clone_geom,
        ras_object,
    ):
        calls["generate"] = {
            "template_plan": template_plan,
            "parameters_df": parameters_df.copy(),
            "apply_fn": apply_fn,
            "suffix": suffix,
            "max_plans_per_batch": max_plans_per_batch,
            "clone_geom": clone_geom,
            "ras_object": ras_object,
        }
        return {"master_log": Path("dummy.csv"), "batch_folders": []}

    def fake_execute_and_summarize(
        plan_matrix,
        max_workers,
        num_cores,
        ras_object,
        timeout_sec,
        clear_geompre,
        force_geompre,
        workers,
    ):
        calls["execute"] = {
            "plan_matrix": plan_matrix,
            "max_workers": max_workers,
            "num_cores": num_cores,
            "ras_object": ras_object,
            "timeout_sec": timeout_sec,
            "clear_geompre": clear_geompre,
            "force_geompre": force_geompre,
            "workers": workers,
        }
        return pd.DataFrame(
            {
                "absolute_perm_id": [1],
                "status": ["not_run"],
                "hdf_path": [np.nan],
            }
        )

    monkeypatch.setattr(
        rascal_module.RasPermutation,
        "define_parameters",
        fake_define_parameters,
    )
    monkeypatch.setattr(
        rascal_module.RasPermutation,
        "generate_plans",
        fake_generate_plans,
    )
    monkeypatch.setattr(
        rascal_module.RasPermutation,
        "execute_and_summarize",
        fake_execute_and_summarize,
    )

    def apply_fn(plan_path, param_row, ras_object=None):
        return None

    workers = [object()]
    calibration_points = [
        CalibrationPoint(
            name="test",
            variable="wse",
            extraction_method="steady_profile",
            observed=100.0,
            river="River",
            reach="Reach",
            station="1",
        )
    ]

    result = RasCalibrate.grid_search(
        template_plan="02",
        parameters={"n_main": [0.0315]},
        apply_fn=apply_fn,
        calibration_points=calibration_points,
        suffix="kzoo_cal",
        max_workers=3,
        num_cores=4,
        force_geompre=True,
        max_plans_per_batch=12,
        clone_geom=True,
        clear_geompre=True,
        timeout_sec=900,
        workers=workers,
    )

    assert result["overall_objective"].isna().all()
    assert calls["generate"]["max_plans_per_batch"] == 12
    assert calls["generate"]["clone_geom"] is True
    assert calls["execute"]["max_workers"] == 3
    assert calls["execute"]["num_cores"] == 4
    assert calls["execute"]["timeout_sec"] == 900
    assert calls["execute"]["clear_geompre"] is True
    assert calls["execute"]["force_geompre"] is True
    assert calls["execute"]["workers"] is workers


def test_evaluate_points_summarizes_failures_at_warning(
    steady_hdf: Path,
    caplog,
) -> None:
    rascal_module = importlib.import_module("ras_commander.RasCalibrate")
    points = [
        CalibrationPoint(
            name="missing upstream",
            variable="wse",
            extraction_method="steady_profile",
            observed=100.0,
            river="River A",
            reach="Reach 1",
            station="999",
            profile_name="PF 1",
        ),
        CalibrationPoint(
            name="missing downstream",
            variable="wse",
            extraction_method="steady_profile",
            observed=101.0,
            river="River A",
            reach="Reach 1",
            station="998",
            profile_name="PF 1",
        ),
    ]

    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasCalibrate"):
        point_results, overall_objective = rascal_module._evaluate_points(
            points,
            steady_hdf,
            metric="rmse",
        )

    warning_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG
    ]

    assert np.isnan(overall_objective)
    assert all(point_result["error"] for point_result in point_results)
    assert warning_messages == [
        "Calibration scoring failed for 2 of 2 point(s) in steady.p01.hdf; "
        "see point_results errors or enable DEBUG logging for details."
    ]
    assert any(
        "missing upstream" in message and str(steady_hdf) in message
        for message in debug_messages
    )


def test_optimize_nelder_mead_advisory_is_debug_only(
    monkeypatch,
    caplog,
) -> None:
    rascal_module = importlib.import_module("ras_commander.RasCalibrate")

    class FakeOptimizeResult:
        def __init__(self, x):
            self.x = np.asarray(x, dtype=float)
            self.success = True
            self.message = "ok"
            self.nit = 1
            self.nfev = 1

    def fake_minimize(objective_fn, x0, method, bounds, options):
        objective_fn(np.asarray(x0, dtype=float))
        return FakeOptimizeResult(x0)

    def fake_evaluate_single(**kwargs):
        return {
            "overall_objective": 1.0,
            "success": True,
            "point_results": [],
        }

    monkeypatch.setattr(rascal_module, "minimize", fake_minimize)
    monkeypatch.setattr(
        rascal_module.RasCalibrate,
        "evaluate_single",
        staticmethod(fake_evaluate_single),
    )

    point = CalibrationPoint(
        name="target",
        variable="wse",
        extraction_method="steady_profile",
        observed=100.0,
        river="River A",
        reach="Reach 1",
        station="100",
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasCalibrate"):
        result = RasCalibrate.optimize(
            plan_number="01",
            parameter_bounds={"n_main": (0.03, 0.04)},
            apply_fn=lambda plan_path, param_row, ras_object=None: None,
            calibration_points=[point],
            max_iterations=1,
        )

    assert result["best_parameters"] == {"n_main": pytest.approx(0.035)}
    assert not any(
        record.levelno >= logging.WARNING
        and "Nelder-Mead bound handling" in record.getMessage()
        for record in caplog.records
    )
    assert any(
        record.levelno == logging.DEBUG
        and "Nelder-Mead bound handling" in record.getMessage()
        and "iteration_history" in record.getMessage()
        for record in caplog.records
    )


def test_optimize_iteration_failure_warning_is_concise(
    monkeypatch,
    caplog,
) -> None:
    rascal_module = importlib.import_module("ras_commander.RasCalibrate")

    class FakeOptimizeResult:
        def __init__(self, x):
            self.x = np.asarray(x, dtype=float)
            self.success = False
            self.message = "stopped"
            self.nit = 1
            self.nfev = 1

    def fake_minimize(objective_fn, x0, method, bounds, options):
        objective_fn(np.asarray(x0, dtype=float))
        return FakeOptimizeResult(x0)

    call_count = {"evaluate_single": 0}

    def fake_evaluate_single(**kwargs):
        call_count["evaluate_single"] += 1
        if call_count["evaluate_single"] == 1:
            raise RuntimeError("solver unavailable")
        return {
            "overall_objective": 2.0,
            "success": True,
            "point_results": [],
        }

    monkeypatch.setattr(rascal_module, "minimize", fake_minimize)
    monkeypatch.setattr(
        rascal_module.RasCalibrate,
        "evaluate_single",
        staticmethod(fake_evaluate_single),
    )

    point = CalibrationPoint(
        name="target",
        variable="wse",
        extraction_method="steady_profile",
        observed=100.0,
        river="River A",
        reach="Reach 1",
        station="100",
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasCalibrate"):
        result = RasCalibrate.optimize(
            plan_number="01",
            parameter_bounds={"n_main": (0.03, 0.04)},
            apply_fn=lambda plan_path, param_row, ras_object=None: None,
            calibration_points=[point],
            method="powell",
            max_iterations=1,
        )

    warning_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG
    ]

    assert not bool(result["iteration_history"].iloc[0]["success"])
    assert warning_messages == [
        "Optimization iteration failed; penalty applied. Enable DEBUG logging "
        "for parameter values and exception details."
    ]
    assert "n_main" not in warning_messages[0]
    assert "solver unavailable" not in warning_messages[0]
    assert any(
        "n_main" in message and "solver unavailable" in message
        for message in debug_messages
    )
