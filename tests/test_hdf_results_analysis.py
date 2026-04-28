from pathlib import Path

import pandas as pd

from ras_commander.hdf.HdfResultsAnalysis import HdfResultsAnalysis
from ras_commander.hdf.HdfResultsPlan import HdfResultsPlan


class FakeAnalysisRasProject:
    def __init__(self, project_folder: Path):
        self.project_folder = Path(project_folder)
        self.project_name = "AnalysisProject"
        self.plan_df = pd.DataFrame(
            [
                {
                    "plan_number": "01",
                    "HDF_Results_Path": str(self.project_folder / "custom" / "Duration6.p01.hdf"),
                },
                {
                    "plan_number": "02",
                    "HDF_Results_Path": str(self.project_folder / "custom" / "Duration12.p02.hdf"),
                },
            ]
        )

    def check_initialized(self):
        return None


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def test_analyze_critical_duration_resolves_plan_hdfs_from_project_assets(
    monkeypatch,
    tmp_path,
):
    ras = FakeAnalysisRasProject(tmp_path)
    _touch(tmp_path / "custom" / "Duration6.p01.hdf")
    _touch(tmp_path / "custom" / "Duration12.p02.hdf")
    observed_paths = []

    def fake_get_reference_timeseries(hdf_path, reftype="lines"):
        observed_paths.append(Path(hdf_path))
        if Path(hdf_path).name == "Duration6.p01.hdf":
            return pd.DataFrame({"Time": [0, 1], "Ref A": [1.0, 2.0]})
        return pd.DataFrame({"Time": [0, 1], "Ref A": [1.5, 3.0]})

    monkeypatch.setattr(
        HdfResultsPlan,
        "get_reference_timeseries",
        staticmethod(fake_get_reference_timeseries),
    )

    result = HdfResultsAnalysis.analyze_critical_duration(
        ["01", "02"],
        plan_labels={"01": "6hr", "02": "12hr"},
        ras_object=ras,
    )

    assert observed_paths == [
        tmp_path / "custom" / "Duration6.p01.hdf",
        tmp_path / "custom" / "Duration12.p02.hdf",
    ]
    assert result.loc[0, "critical_plan"] == "12hr"
    assert result.loc[0, "max_peak"] == 3.0
    assert result.loc[0, "second_peak"] == 2.0


def test_analyze_critical_duration_skips_missing_asset_paths(monkeypatch, tmp_path):
    ras = FakeAnalysisRasProject(tmp_path)
    _touch(tmp_path / "custom" / "Duration6.p01.hdf")

    def fake_get_reference_timeseries(hdf_path, reftype="lines"):
        return pd.DataFrame({"Time": [0, 1], "Ref A": [1.0, 2.0]})

    monkeypatch.setattr(
        HdfResultsPlan,
        "get_reference_timeseries",
        staticmethod(fake_get_reference_timeseries),
    )

    result = HdfResultsAnalysis.analyze_critical_duration(
        ["01", "02"],
        ras_object=ras,
    )

    assert result.loc[0, "critical_plan"] == "01"
    assert pd.isna(result.loc[0, "second_peak"])
