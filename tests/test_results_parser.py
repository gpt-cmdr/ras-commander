from pathlib import Path

import h5py

from ras_commander.RasCmdr import RasCmdr
from ras_commander.results.ResultsParser import ResultsParser


EDGE_LINE_WARNING = (
    "The generated edge lines have self intersections, the interpolation "
    "surface may not generate correctly because of this. See the points "
    "in the error layer."
)


def _write_plan_hdf(path: Path, messages: str) -> None:
    with h5py.File(path, "w") as hdf:
        hdf.create_group("Plan Data/Plan Information")
        hdf.create_dataset(
            "Results/Summary/Compute Messages (text)",
            data=messages.encode("utf-8"),
        )


def test_parse_compute_messages_flags_hecras_data_error_text():
    parsed = ResultsParser.parse_compute_messages(
        "2D Flow Area: MA_3_2DArea\n"
        " - Error generating Mesh. Please review mesh for errors.\n"
        "      Status message = 1 cell(s) with more than 8 sides.\n"
    )

    assert parsed["has_errors"] is True
    assert parsed["error_count"] == 1
    assert parsed["first_error_line"] == (
        "- Error generating Mesh. Please review mesh for errors."
    )


def test_parse_compute_messages_keeps_volume_accounting_error_excluded():
    parsed = ResultsParser.parse_compute_messages(
        "Volume Accounting Error = 0.01 percent\n"
    )

    assert parsed["has_errors"] is False


def test_parse_compute_messages_ignores_new_orleans_error_columns():
    parsed = ResultsParser.parse_compute_messages(
        "Complete Process\t24:22\n"
        "Maximum iteration location\tCell\t WSEL\tERROR\tITERATIONS\n"
        "Pipe Network Iter\tType\tCell\tERROR\tNode or Conduit\n"
        "03OCT2024 08:05:04 Base\tConduit\t9\t0.158\tClaiborne Ave - Conduit 2\n"
        "Error   Percent Error\n"
        "7.319   0.03637\n"
    )

    assert parsed["completed"] is True
    assert parsed["has_errors"] is False
    assert parsed["error_count"] == 0
    assert parsed["first_error_line"] is None


def test_parse_compute_messages_ignores_explicit_zero_error_summaries():
    parsed = ResultsParser.parse_compute_messages(
        "Errors: 0\n0 Errors\nFinished Processing Geometry"
    )

    assert parsed["has_errors"] is False
    assert parsed["error_count"] == 0
    assert parsed["first_error_line"] is None


def test_edge_line_self_intersection_is_a_nonblocking_warning():
    parsed = ResultsParser.parse_compute_messages(
        EDGE_LINE_WARNING + "\n"
        "Finished Steady Flow Simulation\n"
        "Complete Process\t8\n"
    )

    assert parsed["completed"] is True
    assert parsed["has_errors"] is False
    assert parsed["has_warnings"] is True
    assert parsed["warning_count"] == 1
    assert parsed["diagnostics"] == [
        {
            "reason_code": "hec_ras_edge_line_self_intersection",
            "severity": "warning",
            "message": EDGE_LINE_WARNING,
        }
    ]


def test_edge_line_warning_does_not_hide_nearby_true_error():
    parsed = ResultsParser.parse_compute_messages(
        EDGE_LINE_WARNING + " Error generating interpolation surface.\n"
        "Finished Steady Flow Simulation\n"
        "Complete Process\t8\n"
    )

    assert parsed["completed"] is True
    assert parsed["has_errors"] is True
    assert parsed["error_count"] == 1
    assert parsed["diagnostics"] == []


def test_error_layer_text_without_exact_vendor_warning_remains_an_error():
    parsed = ResultsParser.parse_compute_messages(
        "Error generating edge lines. See the points in the error layer.\n"
        "Complete Process\t8\n"
    )

    assert parsed["has_errors"] is True
    assert parsed["error_count"] == 1
    assert parsed["first_error_line"] == (
        "Error generating edge lines. See the points in the error layer."
    )


def test_rascmdr_verification_accepts_completed_hdf_with_edge_line_warning(tmp_path):
    hdf_path = tmp_path / "edge-lines.p01.hdf"
    _write_plan_hdf(
        hdf_path,
        EDGE_LINE_WARNING
        + "\nFinished Steady Flow Simulation\nComplete Process\t8\n",
    )

    assert RasCmdr._verify_completion(hdf_path, check_errors=True) is True


def test_rascmdr_verification_rejects_completed_hdf_with_true_error(tmp_path):
    hdf_path = tmp_path / "edge-lines-error.p01.hdf"
    _write_plan_hdf(
        hdf_path,
        EDGE_LINE_WARNING
        + "\nError generating interpolation surface.\n"
        "Finished Steady Flow Simulation\nComplete Process\t8\n",
    )

    assert RasCmdr._verify_completion(hdf_path, check_errors=True) is False
