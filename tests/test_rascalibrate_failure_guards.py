import importlib

import pandas as pd
import pytest

from ras_commander.RasCalibrate import CalibrationPoint, RasCalibrate


rascalibrate_module = importlib.import_module("ras_commander.RasCalibrate")


def test_grid_search_raises_when_every_permutation_is_unscored(monkeypatch):
    point = CalibrationPoint(
        name="target",
        variable="wse",
        extraction_method="steady_profile",
        observed=1.0,
        river="River",
        reach="Reach",
        station="1000",
    )

    monkeypatch.setattr(
        rascalibrate_module.RasPermutation,
        "define_parameters",
        staticmethod(lambda parameters: pd.DataFrame({"n": [0.04]})),
    )
    monkeypatch.setattr(
        rascalibrate_module.RasPermutation,
        "generate_plans",
        staticmethod(
            lambda *args, **kwargs: {
                "master_log": "unused.csv",
                "batch_folders": [],
            }
        ),
    )
    monkeypatch.setattr(
        rascalibrate_module.RasPermutation,
        "execute_and_summarize",
        staticmethod(
            lambda *args, **kwargs: pd.DataFrame(
                [
                    {
                        "absolute_perm_id": 1,
                        "plan_number": "04",
                        "status": "executed_no_summary",
                        "hdf_path": "missing.p04.hdf",
                    }
                ]
            )
        ),
    )

    with pytest.raises(RuntimeError, match="no finite rmse objective values"):
        RasCalibrate.grid_search(
            template_plan="03",
            parameters={"n": [0.04]},
            apply_fn=lambda plan_path, row, ras_object=None: None,
            calibration_points=[point],
            metric="rmse",
        )


def test_optimize_raises_when_every_evaluation_is_unscored(monkeypatch):
    point = CalibrationPoint(
        name="target",
        variable="wse",
        extraction_method="steady_profile",
        observed=1.0,
        river="River",
        reach="Reach",
        station="1000",
    )

    monkeypatch.setattr(
        RasCalibrate,
        "evaluate_single",
        staticmethod(
            lambda *args, **kwargs: {
                "success": False,
                "overall_objective": float("nan"),
            }
        ),
    )

    with pytest.raises(RuntimeError, match="optimization produced no finite rmse"):
        RasCalibrate.optimize(
            plan_number="03",
            parameter_bounds={"n": (0.02, 0.06)},
            apply_fn=lambda plan_path, row, ras_object=None: None,
            calibration_points=[point],
            metric="rmse",
            max_iterations=1,
        )
