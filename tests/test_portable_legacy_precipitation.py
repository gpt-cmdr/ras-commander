"""Regression tests for legacy rain accounting using synthetic scalar HDF metadata."""

from __future__ import annotations

from pathlib import Path

import h5py
import pandas as pd
import pytest

from ras_commander import RasUnsteady

HERE = Path(__file__).resolve().parent
stage = __import__("ras_commander.remote.PortableExecution", fromlist=["*"])


def legacy_links():
    return pd.DataFrame(
        [
            {
                "dss_part_c": "PRECIP-EXCESS",
                "boundary_index": 0,
                "area_2d": "Area",
                "bc_line_name": "",
                "dss_path": "//Area/PRECIP-EXCESS/01APR3000/30MIN/RUN:1PCT/",
                "use_dss": "True",
            }
        ]
    )


@pytest.fixture
def model(tmp_path, monkeypatch):
    flow = tmp_path / "model.u01"
    plan = tmp_path / "model.p01"
    result = tmp_path / "model.p01.hdf"
    flow.write_text(
        "Flow Title=synthetic legacy rainfall\n"
        "Boundary Location=,,,,,,Area,,,\n"
        "Precipitation Hydrograph= 0\n"
        "DSS Path=//Area/PRECIP-EXCESS/01APR3000/30MIN/RUN:1PCT/\n"
        "Use DSS=True\n"
    )
    plan.write_text("Simulation Date=01Apr3000,0000,08Apr3000,0000\n")
    inline_acre_feet = 1000.0
    window_seconds = 7 * 86400
    discharge = inline_acre_feet * 43560 / window_seconds
    hydrographs = pd.DataFrame([{"interval": "1HOUR", "values": [discharge] * 169}])
    monkeypatch.setattr(
        RasUnsteady, "get_inline_hydrograph_boundaries", lambda *a: hydrographs
    )
    monkeypatch.setattr(RasUnsteady, "get_dss_boundaries", lambda *a: legacy_links())
    monkeypatch.setattr(
        RasUnsteady, "get_met_precipitation_config", lambda *a: {"enabled": False}
    )
    with h5py.File(result, "w") as handle:
        group = handle.create_group(stage._VOLUME_ACCOUNTING_GROUP)
        group.attrs.update(
            {
                "Vol Accounting in": "Acre Feet",
                "Error": 0.0,
                "Error Percent": 0.0,
                "Total Boundary Flux of Water In": 1200.0,
                "Total Boundary Flux of Water Out": 800.0,
                "Volume Starting": 0.0,
                "Volume Ending": 400.0,
                "Precipitation Excess (acre feet)": 200.0,
            }
        )
    return result, flow, plan, inline_acre_feet


def validate(model):
    return stage.validate_unsteady_results(*model[:3])


def test_reported_legacy_rain_explains_synthetic_inline_volume_component(model):
    summary = validate(model)
    assert summary["passed"] and summary["reason_codes"] == []
    r = summary["inflow_reconciliation"]
    assert r["status"] == "passed"
    assert r["authored_inline_inflow_volume"] == pytest.approx(1000.0)
    assert r["reported_legacy_precipitation_volume"] == 200.0
    assert r["authored_inflow_volume"] == pytest.approx(1200.0)
    assert r["relative_difference"] == pytest.approx(0.0, rel=1e-4)
    assert summary["boundary_inflow_volume"] == 1200.0
    rain = summary["legacy_precipitation_accounting"]
    assert not rain["precipitation_independently_validated"]
    assert not rain["hydraulic_approval"]
    assert rain["source_schema"] == "legacy-2d-dss-PRECIP-EXCESS"


def test_no_rain_preserves_inline_validation(model, monkeypatch):
    model[1].write_text("Flow Title=no rainfall\n")
    monkeypatch.setattr(
        RasUnsteady, "get_dss_boundaries", lambda *a: legacy_links().iloc[:0]
    )
    with h5py.File(model[0], "r+") as handle:
        attrs = handle[stage._VOLUME_ACCOUNTING_GROUP].attrs
        del attrs["Precipitation Excess (acre feet)"]
        attrs["Total Boundary Flux of Water In"] = model[3]
    summary = validate(model)
    assert summary["passed"]
    assert summary["inflow_reconciliation"]["reported_legacy_precipitation_volume"] == 0
    assert summary["inflow_reconciliation"]["authored_inflow_volume"] == pytest.approx(
        model[3]
    )


@pytest.mark.parametrize("rain", [None, float("nan"), float("inf"), -1.0, 700000.0])
def test_legacy_rain_missing_invalid_or_larger_than_total_is_rejected(model, rain):
    with h5py.File(model[0], "r+") as handle:
        attrs = handle[stage._VOLUME_ACCOUNTING_GROUP].attrs
        if rain is None:
            del attrs["Precipitation Excess (acre feet)"]
        else:
            attrs["Precipitation Excess (acre feet)"] = rain
    summary = validate(model)
    assert not summary["passed"]
    assert "UNSTEADY_INFLOW_LEGACY_PRECIPITATION_UNVERIFIED" in summary["reason_codes"]
    assert summary["inflow_reconciliation"]["status"] == "not_applicable"


def test_duplicate_legacy_rain_for_one_area_is_ambiguous(model, monkeypatch):
    monkeypatch.setattr(
        RasUnsteady, "get_dss_boundaries", lambda *a: pd.concat([legacy_links()] * 2)
    )
    assert not validate(model)["passed"]


def test_modern_and_legacy_inputs_are_not_double_counted(model, monkeypatch):
    monkeypatch.setattr(
        RasUnsteady, "get_met_precipitation_config", lambda *a: {"enabled": True}
    )
    summary = validate(model)
    assert not summary["passed"]
    assert summary["legacy_precipitation_accounting"]["status"] == "failed"
    assert summary["inflow_reconciliation"]["authored_inflow_volume"] is None


def test_modern_met_only_remains_not_applicable_without_rain_addition(
    model, monkeypatch
):
    model[1].write_text("Flow Title=modern-only precipitation\n")
    monkeypatch.setattr(
        RasUnsteady, "get_met_precipitation_config", lambda *a: {"enabled": True}
    )
    monkeypatch.setattr(
        RasUnsteady, "get_dss_boundaries", lambda *a: legacy_links().iloc[:0]
    )
    summary = validate(model)
    assert summary["passed"]
    assert summary["inflow_reconciliation"]["status"] == "not_applicable"
    assert (
        "UNSTEADY_INFLOW_PRECIPITATION_ENABLED"
        in summary["inflow_reconciliation"]["reasons"]
    )
    assert (
        summary["legacy_precipitation_accounting"]["status"]
        == "modern-precipitation-not-added"
    )


def test_unknown_source_schema_with_positive_reported_rain_is_rejected(
    model, monkeypatch
):
    monkeypatch.setattr(
        RasUnsteady, "get_dss_boundaries", lambda *a: legacy_links().iloc[:0]
    )
    assert not validate(model)["passed"]


def test_mismatch_still_rejected_after_legacy_rain_accounting(model):
    with h5py.File(model[0], "r+") as handle:
        handle[stage._VOLUME_ACCOUNTING_GROUP].attrs[
            "Total Boundary Flux of Water In"
        ] = 900000.0
    summary = validate(model)
    assert (
        not summary["passed"] and "UNSTEADY_INFLOW_MISMATCH" in summary["reason_codes"]
    )


def test_native_weir_raises_are_structured_warnings_and_do_not_change_solver_state():
    messages = """The SA 2D Connection at  CrossingA  Area
The weir elevation will be raised to the minimum cell elevation.
  The weir was raised a maximum of:    12.5 at station:   100.0
The SA 2D Connection at  CrossingB  Area
  The weir was raised a maximum of:     0.25 at station:   75.0
"""
    before = {
        "warning_count": 0,
        "has_warnings": False,
        "completed": True,
        "has_errors": False,
    }
    result = stage._native_geometry_adjustment_diagnostics(messages, before)
    assert result["warning_count"] == 2 and result["has_warnings"]
    assert result["engineering_review_required"]
    assert result["native_geometry_adjustments"][0]["maximum_raise_model_units"] == 12.5
    assert result["native_geometry_adjustments"][0]["station_model_units"] == 100.0
    assert (
        result["native_geometry_adjustments"][1]["connection_context"]
        == "CrossingB  Area"
    )
    assert result["completed"] and not result["has_errors"]
    assert before["warning_count"] == 0
    again = stage._native_geometry_adjustment_diagnostics(messages, result)
    assert again["warning_count"] == 2


@pytest.mark.parametrize("fault", ["wrong_units", "unknown_parameter", "boundary_line"])
def test_legacy_schema_or_units_mismatch_is_rejected(model, monkeypatch, fault):
    links = legacy_links()
    if fault == "wrong_units":
        with h5py.File(model[0], "r+") as handle:
            handle[stage._VOLUME_ACCOUNTING_GROUP].attrs["Vol Accounting in"] = (
                "Cubic Meters"
            )
    elif fault == "unknown_parameter":
        links.loc[0, "dss_part_c"] = "PRECIPITATION"
    else:
        links.loc[0, "bc_line_name"] = "external boundary"
    monkeypatch.setattr(RasUnsteady, "get_dss_boundaries", lambda *a: links)
    assert not validate(model)["passed"]


def test_inline_rain_cannot_hide_behind_valid_legacy_dss_row(model):
    with model[1].open("a") as stream:
        stream.write(
            "Boundary Location=,,,,,,Other,,,\nPrecipitation Hydrograph=2\n1 2\nUse DSS=False\n"
        )
    assert not validate(model)["passed"]


def test_modern_plus_unlisted_inline_legacy_is_rejected(model, monkeypatch):
    model[1].write_text(
        "Boundary Location=,,,,,,Other,,,\nPrecipitation Hydrograph=2\nUse DSS=False\n"
    )
    monkeypatch.setattr(
        RasUnsteady, "get_dss_boundaries", lambda *a: legacy_links().iloc[:0]
    )
    monkeypatch.setattr(
        RasUnsteady, "get_met_precipitation_config", lambda *a: {"enabled": True}
    )
    assert not validate(model)["passed"]


def test_precip_parameter_on_flow_boundary_is_rejected(model):
    with model[1].open("a") as stream:
        stream.write("Flow Hydrograph=0\n")
    assert not validate(model)["passed"]


@pytest.mark.parametrize(
    "keyword", ["Uniform Lateral Inflow Hydrograph=", "Stage and Flow Hydrograph="]
)
def test_other_hydraulic_rain_conflicts_are_rejected(model, keyword):
    with model[1].open("a") as stream:
        stream.write(keyword + "0\n")
    assert not validate(model)["passed"]


def test_non_utf8_comment_without_rain_keeps_existing_validation(model, monkeypatch):
    model[1].write_bytes(b"Flow Title=no rain\n# pin\xf1on\n")
    monkeypatch.setattr(
        RasUnsteady, "get_dss_boundaries", lambda *a: legacy_links().iloc[:0]
    )
    with h5py.File(model[0], "r+") as handle:
        attrs = handle[stage._VOLUME_ACCOUNTING_GROUP].attrs
        del attrs["Precipitation Excess (acre feet)"]
        attrs["Total Boundary Flux of Water In"] = model[3]
    assert validate(model)["passed"]
