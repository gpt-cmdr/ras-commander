"""Reported native excerpts and synthetic controls for classification (#403)."""

import json
from pathlib import Path

import h5py
import pytest

from ras_commander import RasCmdr
from ras_commander.results import ResultsParser


CORPUS = json.loads(
    (Path(__file__).parent / "fixtures/compute_messages/issue403_hecras7_excerpts.json")
    .read_text(encoding="utf-8")
)


@pytest.mark.parametrize("record", CORPUS["records"])
def test_native_fatal_excerpt_overrides_normal_timing_footer(record):
    # The footer is a synthetic completion record, not the retained original.
    messages = record["text"] + "\nComplete Process\t1:26\n"
    result = ResultsParser.parse_compute_messages(messages)
    assert result["completed"]  # Footer presence stays distinct from success.
    assert result["has_errors"] and result["error_count"] == 1
    assert result["first_error_line"] == record["text"]
    assert result["diagnostics"] == [{
        "reason_code": record["reason_code"], "severity": "error",
        "message": record["text"],
    }]
    assert not ResultsParser.is_successful_completion(messages)


@pytest.mark.parametrize("code", ["0", "+0", "-0", "000", "1", "-532462766", "+2", "001"])
def test_exit_code_distinguishes_zero_from_nonzero(code):
    messages = f"Exit Code = {code}\nComplete Process\n"
    result = ResultsParser.parse_compute_messages(messages)
    assert result["has_errors"] is (int(code) != 0)
    assert ResultsParser.is_successful_completion(messages) is (int(code) == 0)


def test_metrics_and_generic_instability_are_not_automatically_fatal():
    messages = (
        "Volume Accounting Error = 0.03\n"
        "Error Node or Conduit\nIterations Cell Error\n"
        "Warning: unstable iteration recovered\nComplete Process\n"
    )
    assert ResultsParser.is_successful_completion(messages)


def test_fatal_record_is_not_hidden_by_metric_exclusion_or_zero_exit():
    messages = (
        "Pipe Flow Solution went unstable in system: Iterations\n"
        "Exit Code = 0\nComplete Process\n"
    )
    assert not ResultsParser.is_successful_completion(messages)


@pytest.mark.parametrize("fatal", [False, True])
def test_hdf_verification_applies_classification_with_existing_structure_checks(tmp_path, fatal):
    messages = "Exit Code = 0\nComplete Process\n"
    if fatal:
        messages = CORPUS["records"][1]["text"] + "\n" + messages
    path = tmp_path / "classification.p01.hdf"
    with h5py.File(path, "w") as hdf:
        hdf.create_group("Plan Data/Plan Information")
        hdf.create_dataset("Results/Summary/Compute Messages (text)", data=messages.encode())
    assert RasCmdr._verify_completion(path, check_errors=True) is (not fatal)
    # Preserve the explicit opt-out from error checking.
    assert RasCmdr._verify_completion(path, check_errors=False)
    with h5py.File(path, "a") as hdf:
        del hdf["Plan Data/Plan Information"]
    assert not RasCmdr._verify_completion(path, check_errors=False)
