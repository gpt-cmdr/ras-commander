"""Logging regressions for RasCheck report exports."""

import logging
from importlib import import_module

from ras_commander.check.report import RasCheckReport
from ras_commander.check.types import CheckResults

report_module = import_module("ras_commander.check.report")
LOGGER_NAME = report_module.logger.name


def _messages(caplog, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == level
    ]


def test_generate_html_logs_filename_at_info_and_full_path_at_debug(tmp_path, caplog):
    report = RasCheckReport(CheckResults())
    output_path = tmp_path / "nested" / "validation_report.html"
    output_path.parent.mkdir()

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        result = report.generate_html(output_path)

    assert result == output_path
    assert output_path.exists()
    info_text = "\n".join(_messages(caplog, logging.INFO))
    debug_text = "\n".join(_messages(caplog, logging.DEBUG))

    assert "Generated HTML report: validation_report.html" in info_text
    assert str(tmp_path) not in info_text
    assert f"Generated HTML report path: {output_path}" in debug_text


def test_export_csv_logs_filename_at_info_and_full_path_at_debug(tmp_path, caplog):
    report = RasCheckReport(CheckResults())
    output_path = tmp_path / "nested" / "messages.csv"
    output_path.parent.mkdir()

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        result = report.export_csv(output_path)

    assert result == output_path
    assert output_path.exists()
    info_text = "\n".join(_messages(caplog, logging.INFO))
    debug_text = "\n".join(_messages(caplog, logging.DEBUG))

    assert "Exported messages to CSV: messages.csv" in info_text
    assert str(tmp_path) not in info_text
    assert f"Exported messages CSV path: {output_path}" in debug_text
