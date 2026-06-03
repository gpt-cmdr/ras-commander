"""
Tests for RasPlan.get_sediment_output_variables / set_sediment_output_variables.

These operate on plain-text plan files, so they use a small synthetic plan
skeleton and run fast without HEC-RAS. Real-HEC-RAS coverage (the requested
variables actually producing the HDF datasets) lives in examples/232.
"""

from __future__ import annotations

import pytest

from ras_commander import RasPlan

_PLAN_WITH_LEVEL = (
    "Plan Title=Sediment Test\n"
    "Program Version=6.60\n"
    "Geom File=g01\n"
    "Flow File=u01\n"
    "Sediment File=s01\n"
    "Run Sediment=-1\n"
    "Sediment Output Level= 3\n"
    "DSS Sediment Output Type= 1\n"
)

_PLAN_WITH_EXISTING_VARS = (
    "Plan Title=Sediment Test\n"
    "Sediment Output Level= 6\n"
    "Sediment Output Variables=2D Cell Manning Total\n"
    "Sediment Output Variables=2D Cell d50 Active\n"
    "DSS Sediment Output Type= 1\n"
)

_PLAN_NO_LEVEL = (
    "Plan Title=Not A Sediment Plan\n"
    "Geom File=g01\n"
)


def _plan(tmp_path, body, name="Test.p01"):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_get_empty_variables(tmp_path):
    p = _plan(tmp_path, _PLAN_WITH_LEVEL)
    info = RasPlan.get_sediment_output_variables(p)
    assert info == {"output_level": 3, "variables": []}


def test_get_existing_variables(tmp_path):
    p = _plan(tmp_path, _PLAN_WITH_EXISTING_VARS)
    info = RasPlan.get_sediment_output_variables(p)
    assert info["output_level"] == 6
    assert info["variables"] == ["2D Cell Manning Total", "2D Cell d50 Active"]


def test_set_adds_variables_and_level(tmp_path):
    p = _plan(tmp_path, _PLAN_WITH_LEVEL)
    RasPlan.set_sediment_output_variables(
        p, ["2D Cell d50 Active", "2D Cell d10 Active", "2D Cell d90 Active"],
        output_level=6)
    info = RasPlan.get_sediment_output_variables(p)
    assert info["output_level"] == 6
    assert info["variables"] == [
        "2D Cell d50 Active", "2D Cell d10 Active", "2D Cell d90 Active"]
    # variables sit directly beneath the level line
    lines = p.read_text().splitlines()
    li = next(i for i, l in enumerate(lines) if l.startswith("Sediment Output Level="))
    assert lines[li + 1] == "Sediment Output Variables=2D Cell d50 Active"


def test_append_dedupes(tmp_path):
    p = _plan(tmp_path, _PLAN_WITH_EXISTING_VARS)
    RasPlan.set_sediment_output_variables(
        p, ["2D Cell d50 Active", "2D Cell d90 Active"], append=True)
    info = RasPlan.get_sediment_output_variables(p)
    # existing 'd50 Active' not duplicated; 'd90 Active' appended; level unchanged
    assert info["variables"] == [
        "2D Cell Manning Total", "2D Cell d50 Active", "2D Cell d90 Active"]
    assert info["output_level"] == 6


def test_replace_mode(tmp_path):
    p = _plan(tmp_path, _PLAN_WITH_EXISTING_VARS)
    RasPlan.set_sediment_output_variables(p, ["2D Cell d90 Active"], append=False)
    info = RasPlan.get_sediment_output_variables(p)
    assert info["variables"] == ["2D Cell d90 Active"]


def test_empty_variables_raises(tmp_path):
    p = _plan(tmp_path, _PLAN_WITH_LEVEL)
    with pytest.raises(ValueError, match="non-empty"):
        RasPlan.set_sediment_output_variables(p, [])


def test_missing_level_raises(tmp_path):
    p = _plan(tmp_path, _PLAN_NO_LEVEL)
    with pytest.raises(ValueError, match="Sediment Output Level"):
        RasPlan.set_sediment_output_variables(p, ["2D Cell d50 Active"])


def test_missing_file_raises(tmp_path):
    # A non-existent path falls through to plan-number resolution (get_plan_path),
    # which raises when there is no initialized project -- consistent with the
    # other RasPlan plan-file editors (e.g. update_simulation_date).
    with pytest.raises((ValueError, RuntimeError)):
        RasPlan.get_sediment_output_variables(tmp_path / "nope.p01")
