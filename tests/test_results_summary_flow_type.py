from pathlib import Path

import pandas as pd

from ras_commander.results.ResultsSummary import ResultsSummary


def _capture_flow_types(monkeypatch, plan_entries, project_folder):
    captured = []

    def fake_summarize_plan(hdf_path, plan_meta):
        captured.append(
            {
                "hdf_path": Path(hdf_path),
                "plan_meta": dict(plan_meta),
            }
        )
        return {
            "plan_number": plan_meta["plan_number"],
            "flow_type": plan_meta["flow_type"],
        }

    monkeypatch.setattr(
        ResultsSummary,
        "summarize_plan",
        staticmethod(fake_summarize_plan),
    )

    df = ResultsSummary.summarize_plans(plan_entries, project_folder)
    return df, captured


def test_summarize_plans_preserves_explicit_flow_type(monkeypatch, tmp_path):
    df, captured = _capture_flow_types(
        monkeypatch,
        [
            {
                "plan_number": "01",
                "plan_title": "Explicit",
                "flow_type": "Steady",
                "unsteady_number": "01",
                "Flow File": "u01",
            }
        ],
        tmp_path,
    )

    assert df["flow_type"].tolist() == ["Steady"]
    assert captured[0]["plan_meta"]["flow_type"] == "Steady"


def test_summarize_plans_uses_unsteady_number_before_flow_file(
    monkeypatch,
    tmp_path,
):
    df, captured = _capture_flow_types(
        monkeypatch,
        [
            {
                "plan_number": "02",
                "plan_title": "Plan DF Row",
                "flow_type": pd.NA,
                "unsteady_number": "02",
                "Flow File": "02",
            }
        ],
        tmp_path,
    )

    assert df["flow_type"].tolist() == ["Unsteady"]
    assert captured[0]["plan_meta"]["flow_type"] == "Unsteady"


def test_summarize_plans_infers_unsteady_from_raw_flow_file(
    monkeypatch,
    tmp_path,
):
    df, captured = _capture_flow_types(
        monkeypatch,
        [
            {
                "plan_number": "03",
                "plan_title": "Raw Flow File",
                "Flow File": "u03",
            }
        ],
        tmp_path,
    )

    assert df["flow_type"].tolist() == ["Unsteady"]
    assert captured[0]["plan_meta"]["flow_type"] == "Unsteady"


def test_summarize_plans_infers_steady_from_raw_flow_path(
    monkeypatch,
    tmp_path,
):
    df, captured = _capture_flow_types(
        monkeypatch,
        [
            {
                "plan_number": "04",
                "plan_title": "Flow Path",
                "Flow Path": tmp_path / "TestProject.f04",
            }
        ],
        tmp_path,
    )

    assert df["flow_type"].tolist() == ["Steady"]
    assert captured[0]["plan_meta"]["flow_type"] == "Steady"


def test_summarize_plans_leaves_bare_numeric_flow_file_unknown(
    monkeypatch,
    tmp_path,
):
    df, captured = _capture_flow_types(
        monkeypatch,
        [
            {
                "plan_number": "05",
                "plan_title": "Ambiguous",
                "Flow File": "05",
            }
        ],
        tmp_path,
    )

    assert df["flow_type"].tolist() == ["Unknown"]
    assert captured[0]["plan_meta"]["flow_type"] == "Unknown"
