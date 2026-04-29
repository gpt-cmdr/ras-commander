from ras_commander.results.ResultsParser import ResultsParser


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
