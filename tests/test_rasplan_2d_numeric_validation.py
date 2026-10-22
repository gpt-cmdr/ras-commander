"""Strict numeric contracts for typed 2D options; no native execution."""

from decimal import Decimal
import os
from pathlib import Path
import shutil

import numpy as np
import pytest

from ras_commander import RasPlan


OPTION_TYPES = {
    key: spec["type"]
    for key, spec in {
        **RasPlan.TWO_D_FLOW_AREA_OPTION_KEYS, **RasPlan.TWO_D_PLAN_OPTION_KEYS,
    }.items()
}
NUMERIC_OPTIONS = [key for key, kind in OPTION_TYPES.items() if kind in {"int", "float", "bool", "equation"}]
INTEGER_OPTIONS = [key for key, kind in OPTION_TYPES.items() if kind == "int"]


class _Ready:
    def check_initialized(self):
        pass


@pytest.mark.parametrize("option", NUMERIC_OPTIONS)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_numeric_option_formatter_rejects_nonfinite(option, value):
    with pytest.raises(ValueError):
        RasPlan._format_2d_option_value(option, value)


@pytest.mark.parametrize("value", [0.9, 1.1, -0.5, np.float64(0.9), Decimal("0.9")])
def test_equation_set_does_not_truncate_numeric_codes(value):
    with pytest.raises(ValueError):
        RasPlan._normalize_2d_equation_set(value)


@pytest.mark.parametrize("option", INTEGER_OPTIONS)
@pytest.mark.parametrize("value", [2.9, -0.5, Decimal("2.9")])
def test_integer_option_formatter_rejects_fractional_values(option, value):
    with pytest.raises(ValueError, match="finite integer"):
        RasPlan._format_2d_option_value(option, value)


@pytest.mark.parametrize("option", INTEGER_OPTIONS)
@pytest.mark.parametrize("raw", ["2.9", "nan", "inf", "-inf"])
def test_stored_integer_options_are_not_truncated_or_nonfinite(option, raw):
    with pytest.raises(ValueError, match="finite integer"):
        RasPlan._coerce_2d_option_value(option, raw)


@pytest.mark.parametrize("option", [key for key, kind in OPTION_TYPES.items() if kind == "float"])
@pytest.mark.parametrize("raw", ["nan", "inf", "-inf"])
def test_stored_nonfinite_numeric_text_is_rejected(option, raw):
    with pytest.raises(ValueError, match="finite"):
        RasPlan._coerce_2d_option_value(option, raw)


@pytest.mark.parametrize("value,expected", [
    (0, 0), (0.0, 0), (1, 1), (1.0, 1), ("DWE", 0),
    ("Diffusion Wave", 0), ("SWE-ELM", 1), ("Shallow Water", 1),
])
def test_equation_finite_codes_and_aliases_preserved(value, expected):
    assert RasPlan._normalize_2d_equation_set(value) == expected


def test_valid_numeric_formatting_and_missing_hdf_values_preserved():
    assert RasPlan._format_2d_option_value("max_iterations", 20.0) == "20"
    assert RasPlan._format_2d_option_value("max_iterations", "20") == "20"
    assert RasPlan._format_2d_option_value("max_iterations", Decimal("20")) == "20"
    assert RasPlan._format_2d_option_value("theta", 0.7) == "0.7"
    assert RasPlan._format_2d_option_value("coriolis", True) == "-1"
    assert RasPlan._format_2d_option_value("boundary_condition_volume_check", 0) == "0"
    # Existing optional HDF missing-value behavior is distinct from serializing
    # nonfinite numeric input or accepting malformed numeric plan text.
    assert RasPlan._coerce_2d_option_value("theta", float("nan")) is None
    assert RasPlan._coerce_2d_option_value("theta", "") is None


@pytest.mark.parametrize("option", INTEGER_OPTIONS + ["equation_set"])
@pytest.mark.parametrize("value", [True, False, np.bool_(True)])
def test_integer_and_equation_options_reject_boolean_values(option, value):
    with pytest.raises(ValueError):
        RasPlan._format_2d_option_value(option, value)


@pytest.mark.parametrize("option", [key for key, kind in OPTION_TYPES.items() if kind == "bool"])
@pytest.mark.parametrize("value", [0.9, -0.5, 2, -2])
def test_boolean_options_reject_truncation_and_unknown_numeric_codes(option, value):
    with pytest.raises(ValueError):
        RasPlan._format_2d_option_value(option, value)
    with pytest.raises(ValueError):
        RasPlan._coerce_2d_option_value(option, value)


@pytest.mark.parametrize("value,expected", [
    (True, "-1"), (False, "0"), (-1, "-1"), (0, "0"), (1, "-1"),
    ("-1", "-1"), ("True", "-1"), ("False", "0"), (np.bool_(True), "-1"),
])
def test_documented_native_boolean_encodings_and_aliases_are_preserved(value, expected):
    assert RasPlan._format_2d_option_value("coriolis", value) == expected


@pytest.fixture
def retained_plan_copy(tmp_path):
    root = Path(os.environ.get(
        "RAS_COMMANDER_2D_OPTION_FIXTURES",
        "tests/data/external/golden",
    ))
    source = root / "701/BaldEagleCrkMulti2D/p03/F3_refpts_lines/BaldEagleDamBrk.p03"
    if not source.is_file():
        pytest.skip("Set RAS_COMMANDER_2D_OPTION_FIXTURES to retained F3 corpus")
    before = source.read_bytes()
    target = tmp_path / source.name
    shutil.copy2(source, target)
    yield target
    assert source.read_bytes() == before


@pytest.mark.parametrize("option,value", [
    ("equation_set", 0.9), ("max_iterations", 2.9), ("theta", float("nan")),
    ("theta", float("inf")), ("cores", float("inf")),
    ("time_step_use_courant", float("nan")),
    ("coriolis", 0.9), ("max_iterations", True),
])
def test_public_setter_rejects_invalid_input_without_changing_real_copy(retained_plan_copy, option, value):
    before = retained_plan_copy.read_bytes()
    with pytest.raises(ValueError):
        RasPlan.set_2d_flow_options(
            retained_plan_copy, mesh_name="BaldEagleCr", options={option: value}, ras_object=_Ready(),
        )
    assert retained_plan_copy.read_bytes() == before


def test_public_setter_valid_partial_update_on_real_copy(retained_plan_copy):
    before = RasPlan.get_2d_flow_options(retained_plan_copy, ras_object=_Ready())
    RasPlan.set_2d_flow_options(
        retained_plan_copy, mesh_name="BaldEagleCr", max_iterations=23.0,
        theta=0.8, equation_set="SWE-ELM", ras_object=_Ready(),
    )
    after = RasPlan.get_2d_flow_options(retained_plan_copy, ras_object=_Ready())
    assert after["plan"] == before["plan"]
    assert after["default"] == before["default"]
    for key, value in before["areas"][0].items():
        if key not in {"max_iterations", "theta", "equation_set"}:
            assert after["areas"][0][key] == value
    assert after["areas"][0]["max_iterations"] == 23
    assert after["areas"][0]["theta"] == 0.8
    assert after["areas"][0]["equation_set"] == "SWE-ELM"
