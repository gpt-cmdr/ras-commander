"""Regression tests for Monte Carlo breach-parameter field mapping."""

from __future__ import annotations

import pandas as pd
import pytest

from ras_commander.RasBreach import RasBreach
from ras_commander.RasMonteCarlo import RasMonteCarlo


RAW_BREACH_GEOM = "5700,200,595,0.5,0.5,True,0.5,630,2,2.6"


def _capture_breach_update(monkeypatch, raw_breach_geom=RAW_BREACH_GEOM):
    captured = {}

    def read_breach_block(*args, **kwargs):
        return {"values": {"Breach Geom": raw_breach_geom}}

    def update_breach_block(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(RasBreach, "read_breach_block", read_breach_block)
    monkeypatch.setattr(RasBreach, "update_breach_block", update_breach_block)
    return captured


def test_default_breach_mapping_uses_final_width_and_formation_time_slot(monkeypatch):
    captured = _capture_breach_update(monkeypatch)
    apply_fn = RasMonteCarlo.make_breach_apply_fn("Dam")

    apply_fn(
        "project.p01",
        pd.Series(
            {
                "breach_width": 250.0,
                "breach_formation_time": 1.25,
            }
        ),
    )

    geom = captured["geom_values"]
    assert geom[1] == 250.0
    assert geom[8] == 1.25
    assert geom[9] == "2.6"


def test_explicit_breach_mapping_updates_canonical_slots(monkeypatch):
    captured = _capture_breach_update(monkeypatch)
    apply_fn = RasMonteCarlo.make_breach_apply_fn(
        "Dam",
        {
            "failure_mode": "mode",
            "piping_coefficient": "pipe_coef",
            "initial_piping_elevation": "pipe_elev",
            "weir_coefficient": "weir",
        },
    )

    apply_fn(
        "project.p01",
        pd.Series(
            {
                "mode": "overtopping",
                "pipe_coef": 0.75,
                "pipe_elev": 625.0,
                "weir": 3.0,
            }
        ),
    )

    geom = captured["geom_values"]
    assert geom[5] is False
    assert geom[6] == 0.75
    assert geom[7] == 625.0
    assert geom[8] == "2"
    assert geom[9] == 3.0


def test_nine_field_record_preserves_arity_for_formation_time(monkeypatch):
    captured = _capture_breach_update(
        monkeypatch,
        "5250,400,595,2,2,True,0.8,620,1",
    )
    apply_fn = RasMonteCarlo.make_breach_apply_fn(
        "Dam",
        {"formation_time": "time"},
    )

    apply_fn("project.p05", pd.Series({"time": 1.5}))

    geom = captured["geom_values"]
    assert len(geom) == 9
    assert geom[8] == 1.5


def test_nine_field_record_appends_only_requested_weir_coefficient(monkeypatch):
    captured = _capture_breach_update(
        monkeypatch,
        "5250,400,595,2,2,True,0.8,620,1",
    )
    apply_fn = RasMonteCarlo.make_breach_apply_fn(
        "Dam",
        {"weir_coefficient": "weir"},
    )

    apply_fn("project.p05", pd.Series({"weir": 2.6}))

    geom = captured["geom_values"]
    assert len(geom) == 10
    assert geom[8:] == ["1", 2.6]


@pytest.mark.parametrize("failure_mode", ["piping", True, 1, 1.0, "1"])
def test_failure_mode_piping_coercion(monkeypatch, failure_mode):
    captured = _capture_breach_update(monkeypatch)
    apply_fn = RasMonteCarlo.make_breach_apply_fn(
        "Dam",
        {"failure_mode": "mode"},
    )

    apply_fn("project.p01", pd.Series({"mode": failure_mode}))

    assert captured["geom_values"][5] is True


def test_failure_mode_rejects_ambiguous_value(monkeypatch):
    _capture_breach_update(monkeypatch)
    apply_fn = RasMonteCarlo.make_breach_apply_fn(
        "Dam",
        {"failure_mode": "mode"},
    )

    with pytest.raises(ValueError, match="failure_mode must be"):
        apply_fn("project.p01", pd.Series({"mode": "triggered"}))


def test_failure_mode_rejects_nonbinary_numeric_value(monkeypatch):
    _capture_breach_update(monkeypatch)
    apply_fn = RasMonteCarlo.make_breach_apply_fn(
        "Dam",
        {"failure_mode": "mode"},
    )

    with pytest.raises(ValueError, match="exactly 1 or 0"):
        apply_fn("project.p01", pd.Series({"mode": 2.0}))


def test_safe_legacy_breach_targets_warn_and_preserve_intent(monkeypatch):
    captured = _capture_breach_update(monkeypatch)

    with pytest.warns(FutureWarning) as warnings_seen:
        apply_fn = RasMonteCarlo.make_breach_apply_fn(
            "Dam",
            {"initial_width": "width", "weir_coef": "weir"},
        )

    assert len(warnings_seen) == 2
    apply_fn("project.p01", pd.Series({"width": 275.0, "weir": 3.1}))

    geom = captured["geom_values"]
    assert geom[1] == 275.0
    assert geom[6] == "0.5"
    assert geom[9] == 3.1


def test_canonical_and_legacy_alias_conflict_is_rejected():
    with pytest.warns(FutureWarning):
        with pytest.raises(ValueError, match="mapped more than once"):
            RasMonteCarlo.make_breach_apply_fn(
                "Dam",
                {
                    "final_bottom_width": "canonical_width",
                    "initial_width": "legacy_width",
                },
            )


@pytest.mark.parametrize("legacy_target", ["active", "top_elev", "formation_method"])
def test_unsafe_legacy_breach_targets_fail_before_apply(legacy_target):
    with pytest.raises(ValueError, match=legacy_target):
        RasMonteCarlo.make_breach_apply_fn(
            "Dam",
            {legacy_target: "sample_value"},
        )


@pytest.mark.parametrize(
    "mapping",
    [
        {"active": "is_active"},
        {"formation_time": "method"},
        {"initial_width": "weir_coefficient"},
    ],
)
def test_mapping_with_targets_on_both_sides_is_rejected(mapping):
    with pytest.raises(ValueError, match="both sides are recognized targets"):
        RasMonteCarlo.make_breach_apply_fn("Dam", mapping)


def test_real_plan_text_integration_updates_correct_fields(tmp_path):
    plan_path = tmp_path / "BreachProject.p01"
    plan_path.write_text(
        "Plan Title=Monte Carlo Breach Integration\r\n"
        "Breach Loc=River,Reach,1000,True,Dam\r\n"
        "Breach Method= 0\r\n"
        "Breach Geom=5700,200,595,0.5,0.5,True,0.5,630,2,2.6\r\n"
        "Breach Start= 0,\r\n"
        "Breach Progression= 0\r\n"
        "Breach Calculator Data= 0,0,0,0,0,0,0\r\n",
        encoding="utf-8",
        newline="",
    )
    apply_fn = RasMonteCarlo.make_breach_apply_fn(
        "Dam",
        {
            "formation_time": "time",
            "weir_coefficient": "weir",
        },
    )

    apply_fn(plan_path, pd.Series({"time": 1.0, "weir": 3.0}))

    updated = RasBreach.read_breach_block(plan_path, "Dam")
    fields = updated["values"]["Breach Geom"].split(",")
    assert fields == [
        "5700",
        "200",
        "595",
        "0.5",
        "0.5",
        "True",
        "0.5",
        "630",
        "1.0",
        "3.0",
    ]
