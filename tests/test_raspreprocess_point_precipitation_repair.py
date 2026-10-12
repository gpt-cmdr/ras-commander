"""Bounded CompletePreProcess repair of intermittent point-precipitation failures.

HEC-RAS's RasProcess.exe CompletePreProcess can write no point precipitation
for identical inputs and Ras.exe still exits 0. preprocess_plan re-runs only
that step on the same temporary HDF. These tests replace both executables with
fakes; the HDF fixtures use the real Event Conditions layout.
"""

import subprocess

import pytest
from test_preprocess_event_conditions import _event_hdf
from test_raspreprocess_gridded_precipitation import (
    _ExitedProcess,
    _patch_launch,
    _seed_project,
)

from ras_commander.RasPreprocess import RasPreprocess

NO_VALID = (
    "Processing Precipitation data...\n"
    "No valid precipitation time-series data found for this time-window: "
    "(1/1/2024 12:00:00 AM) -> (1/5/2024 12:00:00 AM)\n"
    "Error processing Precipitation data, exiting...\n"
)


class _RepairProcess:
    pid = 4242

    def __init__(self, returncode=0):
        self.returncode = returncode

    def poll(self):
        return self.returncode


class _Harness:
    """Fake Ras.exe launch plus scripted RasProcess.exe repair outcomes."""

    def __init__(self, tmp_path, monkeypatch, *, mode="Point", outcomes=(),
                 artifacts=("b", "x"), rasprocess=True, rasmap=True):
        self.tmp_path = tmp_path
        self.tmp_hdf = tmp_path / "fixture.p01.tmp.hdf"
        self.x_file = tmp_path / "fixture.x03"
        self.outcomes = list(outcomes)
        self.repair_calls = []
        self.residue_calls = []
        self.ras = _seed_project(tmp_path)
        (tmp_path / "fixture.u02").write_text(
            f"Precipitation Mode=Enable\nMet BC=Precipitation|Mode={mode}\n"
        )
        if rasprocess:
            (tmp_path / "RasProcess.exe").write_bytes(b"fixture executable")
        if rasmap:
            (tmp_path / "fixture.rasmap").write_text("<RASMapper />\n")
        harness = self

        class Monitor:
            blocked_reason = None
            signal_source = None

            @staticmethod
            def enable_detailed_logging(_path):
                return True

            def __init__(self, **_kwargs):
                pass

            def monitor_until_signal(self, _process):
                # Ras.exe exits 0 before any readiness signal, leaving the
                # temporary HDF without completed point precipitation.
                _event_hdf(harness.tmp_hdf, complete=False, values=False, mode=mode)
                if "b" in artifacts:
                    (harness.tmp_path / "fixture.b01").write_bytes(b"ready")
                if "x" in artifacts:
                    harness.x_file.write_bytes(b"GEOM\r\nLINE\r\n")
                return False

        launcher = _ExitedProcess()
        _patch_launch(monkeypatch, Monitor, launcher, [])

        def popen(command, **kwargs):
            if not str(command[0]).endswith("RasProcess.exe"):
                return launcher
            self.repair_calls.append((list(command), kwargs.get("cwd")))
            complete, text, returncode = self.outcomes.pop(0)
            kwargs["stdout"].write(text)
            kwargs["stdout"].flush()
            _event_hdf(self.tmp_hdf, complete=complete, values=complete, mode=mode)
            return _RepairProcess(returncode)

        monkeypatch.setattr(subprocess, "Popen", popen)
        monkeypatch.setattr(
            RasPreprocess,
            "_terminate_exact_preprocess_residue",
            staticmethod(lambda **kwargs: (self.residue_calls.append(kwargs), ((), ()))[1]),
        )
        monkeypatch.setattr(
            RasPreprocess,
            "_detect_first_run_tcu_dialog",
            staticmethod(lambda _pid=None: None),
        )

    def run(self, **kwargs):
        kwargs.setdefault("max_wait", 2)
        return RasPreprocess.preprocess_plan(
            "01", ras_object=self.ras, clear_existing=False, **kwargs
        )


FAIL = (False, NO_VALID, 0)
PASS = (True, "Processing Precipitation data...\nFinished\n", 0)


def test_repair_succeeds_on_second_attempt_and_fixes_line_endings(tmp_path, monkeypatch):
    harness = _Harness(tmp_path, monkeypatch, outcomes=[FAIL, PASS])

    result = harness.run()

    assert result.success, result.error
    assert result.signal_source == "completepreprocess_repair"
    assert result.tmp_hdf_path == harness.tmp_hdf
    first, second = result.precipitation_repair_attempts
    assert first["attempt"] == 1 and second["attempt"] == 2
    assert first["return_code"] == 0 and second["return_code"] == 0
    assert first["no_valid_precipitation"] is True
    assert second["no_valid_precipitation"] is False
    assert any("Completed Successfully" in e for e in first["validation_errors"])
    assert any("Precipitation/Values" in e for e in first["validation_errors"])
    assert second["validation_errors"] == []
    assert all(isinstance(r["elapsed_seconds"], float) for r in (first, second))
    assert all(r["timed_out"] is False and r["error"] is None for r in (first, second))
    # The early-return failure path skipped this; a repaired success must not.
    assert harness.x_file.read_bytes() == b"GEOM\nLINE\n"
    # Exact-plan residue cleanup after the Ras.exe launch and after each attempt.
    assert len(harness.residue_calls) == 3
    assert all(c["tmp_hdf"] == harness.tmp_hdf for c in harness.residue_calls)


def test_repair_runs_completepreprocess_from_project_folder(tmp_path, monkeypatch):
    harness = _Harness(tmp_path, monkeypatch, outcomes=[PASS])

    assert harness.run(fix_line_endings=False)

    (command, cwd), = harness.repair_calls
    assert command == [
        str(tmp_path / "RasProcess.exe"),
        "CompletePreProcess",
        str(tmp_path / "fixture.rasmap"),
        str(harness.tmp_hdf),
    ]
    # Gauge DSS paths in the HDF are relative and resolve against the cwd.
    assert cwd == str(tmp_path)


def test_all_repair_attempts_fail_with_clear_error(tmp_path, monkeypatch):
    harness = _Harness(tmp_path, monkeypatch, outcomes=[FAIL, FAIL, (False, "", 3)])

    result = harness.run(precipitation_repair_attempts=3)

    assert not result.success
    assert result.signal_source == "natural_completion"
    assert result.error.startswith("Preprocessing is incomplete: ")
    assert "Completed Successfully" in result.error
    assert "CompletePreProcess 3 time(s) did not complete point precipitation" in result.error
    assert "attempt 1: exit 0, 'No valid precipitation' reported" in result.error
    assert "attempt 3: exit 3" in result.error
    assert [r["attempt"] for r in result.precipitation_repair_attempts] == [1, 2, 3]
    assert harness.outcomes == []
    assert harness.x_file.read_bytes() == b"GEOM\r\nLINE\r\n"


def test_nonzero_exit_is_not_accepted_even_when_hdf_validates(tmp_path, monkeypatch):
    harness = _Harness(tmp_path, monkeypatch, outcomes=[(True, "", 1), PASS])

    result = harness.run(fix_line_endings=False)

    assert result.success
    assert [r["return_code"] for r in result.precipitation_repair_attempts] == [1, 0]


def test_repair_disabled(tmp_path, monkeypatch):
    harness = _Harness(tmp_path, monkeypatch, outcomes=[PASS])

    result = harness.run(precipitation_repair_attempts=0)

    assert not result.success
    assert "Preprocessing is incomplete" in result.error
    assert result.precipitation_repair_attempts == []
    assert harness.repair_calls == []


@pytest.mark.parametrize("artifacts", [("x",), ("b",), ()])
def test_repair_not_attempted_without_b_and_x_files(tmp_path, monkeypatch, artifacts):
    harness = _Harness(tmp_path, monkeypatch, outcomes=[PASS], artifacts=artifacts)

    result = harness.run()

    assert not result.success
    assert "Preprocessing did not generate" in result.error
    assert result.precipitation_repair_attempts == []
    assert harness.repair_calls == []


@pytest.mark.parametrize("mode", ["Gridded", "Uniform"])
def test_repair_not_attempted_for_non_point_modes(tmp_path, monkeypatch, mode):
    harness = _Harness(tmp_path, monkeypatch, mode=mode, outcomes=[PASS])

    result = harness.run()

    assert not result.success
    assert result.precipitation_repair_attempts == []
    assert harness.repair_calls == []


def test_repair_not_attempted_when_precipitation_disabled(tmp_path, monkeypatch):
    harness = _Harness(tmp_path, monkeypatch, outcomes=[PASS])
    (tmp_path / "fixture.u02").write_text(
        "Precipitation Mode=Disable\nMet BC=Precipitation|Mode=Point\n"
    )

    result = harness.run()

    assert not result.success
    assert "Completed Successfully" in result.error
    assert harness.repair_calls == []


@pytest.mark.parametrize(
    "missing,detail",
    [("rasprocess", "RasProcess.exe not found"), ("rasmap", "fixture.rasmap not found")],
)
def test_repair_reports_missing_prerequisites(tmp_path, monkeypatch, missing, detail):
    harness = _Harness(
        tmp_path,
        monkeypatch,
        outcomes=[PASS],
        rasprocess=missing != "rasprocess",
        rasmap=missing != "rasmap",
    )

    result = harness.run()

    assert not result.success
    assert "Point-precipitation repair not attempted" in result.error
    assert detail in result.error
    assert harness.repair_calls == []


def test_repair_timeout_terminates_attempt_and_stops(tmp_path, monkeypatch):
    harness = _Harness(tmp_path, monkeypatch)
    terminated = []

    class Hung(_RepairProcess):
        def __init__(self):
            super().__init__(returncode=None)

    def popen(command, **kwargs):
        if not str(command[0]).endswith("RasProcess.exe"):
            return _ExitedProcess()
        harness.repair_calls.append((list(command), kwargs.get("cwd")))
        return Hung()

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(
        RasPreprocess,
        "_terminate_process_tree",
        staticmethod(lambda child: (terminated.append(child), setattr(child, "returncode", 1))),
    )

    result = harness.run(precipitation_repair_timeout=1)

    assert not result.success
    assert len(harness.repair_calls) == 1
    (record,) = result.precipitation_repair_attempts
    assert record["timed_out"] is True
    assert "timed out after 1 seconds" in record["error"]
    assert "Repair stopped early" in result.error
    assert len(terminated) == 1
