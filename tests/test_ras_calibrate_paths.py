from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from ras_commander.RasCalibrate import _resolve_plan_hdf_path


class FakeCalibrationRasProject:
    def __init__(self, project_folder: Path, plan_df: pd.DataFrame):
        self.project_folder = Path(project_folder)
        self.project_name = "CalibProject"
        self.plan_df = plan_df

    def get_plan_entries(self):
        return self.plan_df


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def test_resolve_plan_hdf_path_prefers_compute_result_row(tmp_path):
    compute_hdf = _touch(tmp_path / "compute" / "Result.p03.hdf")
    ras = FakeCalibrationRasProject(
        tmp_path,
        pd.DataFrame(
            [{"plan_number": "03", "HDF_Results_Path": str(tmp_path / "stale.p03.hdf")}]
        ),
    )
    compute_result = SimpleNamespace(
        results_df_row={"HDF_Results_Path": str(compute_hdf)}
    )

    assert _resolve_plan_hdf_path("03", ras_object=ras, compute_result=compute_result) == compute_hdf


def test_resolve_plan_hdf_path_uses_project_asset_resolution(tmp_path):
    custom_hdf = _touch(tmp_path / "custom" / "Calibration.p04.hdf")
    ras = FakeCalibrationRasProject(
        tmp_path,
        pd.DataFrame([{"plan_number": "04", "HDF_Results_Path": str(custom_hdf)}]),
    )

    assert _resolve_plan_hdf_path("p04", ras_object=ras) == custom_hdf


def test_resolve_plan_hdf_path_keeps_project_name_fallback(tmp_path):
    fallback_hdf = _touch(tmp_path / "CalibProject.p05.hdf")
    ras = FakeCalibrationRasProject(
        tmp_path,
        pd.DataFrame([{"plan_number": "05", "HDF_Results_Path": None}]),
    )

    assert _resolve_plan_hdf_path("05", ras_object=ras) == fallback_hdf


def test_resolve_plan_hdf_path_reports_missing_hdf(tmp_path):
    ras = FakeCalibrationRasProject(
        tmp_path,
        pd.DataFrame([{"plan_number": "06", "HDF_Results_Path": None}]),
    )

    with pytest.raises(FileNotFoundError, match="plan 06"):
        _resolve_plan_hdf_path("06", ras_object=ras)
