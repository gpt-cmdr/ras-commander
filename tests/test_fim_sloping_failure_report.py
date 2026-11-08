"""Engine exit/report precedence at the real sloping protocol boundary."""
import json

import pytest

from ras_commander.fim import _engine, _sloping
from ras_commander.fim.errors import FimEngineError


@pytest.mark.parametrize("report", [None, "invalid", '{"status":"complete"}'])
def test_early_budget_failure_preserves_exit_and_detail(tmp_path, report):
    path = tmp_path / "report.json"
    if report is not None:
        path.write_text(report, encoding="utf-8")
    with pytest.raises(FimEngineError, match="exit 1: budget exceeded: sloping decoder plan exceeds budget"):
        _sloping._read_report(path, 1, "budget exceeded: sloping decoder plan exceeds budget\n")


@pytest.mark.parametrize("report", [None, '{"error":"unsupported: terrain history"}'])
def test_early_unsupported_failure_retains_refusal_type(tmp_path, report):
    path = tmp_path / "report.json"
    if report is not None:
        path.write_text(report, encoding="utf-8")
    with pytest.raises(_engine.EngineRefusal, match="unsupported: terrain history"):
        _sloping._read_report(path, 1, "unsupported: terrain history")


@pytest.mark.parametrize("report", [None, "invalid", b"\xff"])
def test_success_exit_still_requires_a_valid_report(tmp_path, report):
    path = tmp_path / "report.json"
    if isinstance(report, bytes):
        path.write_bytes(report)
    elif report is not None:
        path.write_text(report, encoding="utf-8")
    with pytest.raises(FimEngineError, match="Missing or invalid sloping engine report"):
        _sloping._read_report(path, 0, "")


def test_success_report_reaches_existing_semantic_validation(tmp_path):
    path = tmp_path / "report.json"
    report = {"status": "complete", "profiles": []}
    path.write_text(json.dumps(report), encoding="utf-8")
    assert _sloping._read_report(path, 0, "") == report


def test_failed_exit_without_stderr_is_still_explicit(tmp_path):
    with pytest.raises(FimEngineError, match="exit 9: no diagnostic on stderr"):
        _sloping._read_report(tmp_path / "report.json", 9, "")
