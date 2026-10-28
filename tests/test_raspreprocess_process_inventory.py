"""Process inventory regressions for Wine's unreadable command lines."""

from types import SimpleNamespace

import psutil
import pytest

from ras_commander import RasPreprocess


def _query_both(tmp_path):
    temporary = tmp_path / "fixture.p01.tmp.hdf"
    writers = RasPreprocess._active_complete_preprocess_writers(temporary, 1000.0)
    cleanup = RasPreprocess._terminate_exact_preprocess_residue(
        tmp_path / "fixture.prj", tmp_path / "fixture.p01", temporary, 1000.0,
    )
    return writers, cleanup


def test_unrelated_command_line_and_creation_time_are_never_queried(tmp_path, monkeypatch):
    class Unrelated:
        info = {"pid": 10, "name": "unrelated.exe"}

        def cmdline(self):
            raise AssertionError("Unrelated command line must not be queried")

        def create_time(self):
            raise AssertionError("Unrelated creation time must not be queried")

    def inventory(attributes):
        assert attributes == ["pid", "name"]
        return iter([Unrelated()])

    monkeypatch.setattr(psutil, "process_iter", inventory)
    assert _query_both(tmp_path) == ((), ((), ()))


@pytest.mark.parametrize("name", ["Ras.exe", "RasProcess.exe"])
@pytest.mark.parametrize("failure", [OSError(87, "Invalid parameter"), psutil.AccessDenied(20)])
def test_unreadable_ras_command_line_fails_closed(tmp_path, monkeypatch, name, failure):
    class PotentialRas:
        info = {"pid": 20, "name": name}

        def cmdline(self):
            raise failure

    monkeypatch.setattr(psutil, "process_iter", lambda _attributes: iter([PotentialRas()]))
    assert _query_both(tmp_path) == ((-1,), ((), (-1,)))


@pytest.mark.parametrize("name", [None, "", " "])
def test_unknown_process_name_fails_closed(tmp_path, monkeypatch, name):
    process = SimpleNamespace(info={"pid": 30, "name": name})
    monkeypatch.setattr(psutil, "process_iter", lambda _attributes: iter([process]))
    assert _query_both(tmp_path) == ((-1,), ((), (-1,)))


@pytest.mark.parametrize("yield_candidate_first", [False, True])
def test_iterator_oserror_fails_closed_before_any_cleanup(
    tmp_path, monkeypatch, yield_candidate_first,
):
    class Writer:
        info = {
            "pid": 40, "name": "RasProcess.exe", "create_time": 1001.0,
            "cmdline": ["RasProcess.exe", "CompletePreProcess", str(tmp_path / "fixture.p01.tmp.hdf")],
        }

        def terminate(self):
            raise AssertionError("Incomplete inventory cannot authorize cleanup")

    def inventory(_attributes):
        if yield_candidate_first:
            yield Writer()
        raise OSError(87, "Invalid parameter during iterator prefetch")

    monkeypatch.setattr(psutil, "process_iter", inventory)
    assert _query_both(tmp_path) == ((-1,), ((), (-1,)))


def test_ras_fields_are_queried_after_name_filtering(tmp_path, monkeypatch):
    calls = []
    temporary = tmp_path / "fixture.p01.tmp.hdf"

    class Writer:
        info = {"pid": 50, "name": "RasProcess.exe"}

        def cmdline(self):
            calls.append("cmdline")
            return ["RasProcess.exe", "CompleteEventConditions", str(temporary)]

        def create_time(self):
            calls.append("create_time")
            return 1001.0

    monkeypatch.setattr(psutil, "process_iter", lambda _attributes: iter([Writer()]))
    assert RasPreprocess._active_complete_preprocess_writers(temporary, 1000.0) == (50,)
    assert calls == ["cmdline", "create_time"]


def test_disappeared_process_is_not_an_unknown_writer(tmp_path, monkeypatch):
    class Disappeared:
        info = {"pid": 60, "name": "RasProcess.exe"}

        def cmdline(self):
            raise psutil.NoSuchProcess(60)

    monkeypatch.setattr(psutil, "process_iter", lambda _attributes: iter([Disappeared()]))
    assert _query_both(tmp_path) == ((), ((), ()))


def test_unreadable_creation_time_fails_closed(tmp_path, monkeypatch):
    class PotentialRas:
        info = {"pid": 70, "name": "RasProcess.exe"}

        def cmdline(self):
            return ["RasProcess.exe", "CompleteEventConditions"]

        def create_time(self):
            raise OSError(87, "Invalid parameter")

    monkeypatch.setattr(psutil, "process_iter", lambda _attributes: iter([PotentialRas()]))
    assert _query_both(tmp_path) == ((-1,), ((), (-1,)))


@pytest.mark.parametrize("arguments", [None, [], "RasProcess.exe"])
def test_incomplete_ras_command_line_fails_closed(tmp_path, monkeypatch, arguments):
    process = SimpleNamespace(info={
        "pid": 80, "name": "RasProcess.exe", "create_time": 1001.0,
        "cmdline": arguments,
    })
    monkeypatch.setattr(psutil, "process_iter", lambda _attributes: iter([process]))
    assert _query_both(tmp_path) == ((-1,), ((), (-1,)))


def test_unknown_inventory_never_inspects_artifacts(tmp_path, monkeypatch):
    def inventory(_attributes):
        raise OSError(87, "Invalid parameter")

    def artifact_read(*_arguments, **_keywords):
        raise AssertionError("Unknown ownership cannot authorize artifact reads")

    monkeypatch.setattr(psutil, "process_iter", inventory)
    monkeypatch.setattr(RasPreprocess, "_artifact_state", artifact_read)
    monkeypatch.setattr(RasPreprocess, "_preprocessing_artifacts_ready", artifact_read)
    assert RasPreprocess._completepreprocess_handoff_ready(
        tmp_path / "fixture.p01.tmp.hdf", tmp_path / "fixture.b01",
        tmp_path / "fixture.x01", {"completepreprocess_seen": True},
        started_at=1000.0,
    ) is False


@pytest.mark.parametrize("recovered_name", ["unrelated.exe", "RasProcess.exe"])
def test_recovered_process_name_is_used_for_writer_detection(tmp_path, monkeypatch, recovered_name):
    from ras_commander import _process_inspection as inspection

    temporary = tmp_path / "fixture.p01.tmp.hdf"
    process = SimpleNamespace(info={
        "pid": 90, "name": None, "create_time": 1001.0,
        "cmdline": ["RasProcess.exe", "CompletePreProcess", str(temporary)],
    }, create_time=lambda: 1001.0, ppid=lambda: 100)
    monkeypatch.setattr(psutil, "process_iter", lambda _attrs: iter([process]))
    monkeypatch.setattr(inspection, "_WINDOWS_PROCESS_NAMES", True)
    monkeypatch.setattr(inspection, "_windows_process_snapshot_name", lambda pid: recovered_name)
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(pid=pid, create_time=lambda: 1001.0))
    expected = (90,) if recovered_name == "RasProcess.exe" else ()
    assert RasPreprocess._active_complete_preprocess_writers(temporary, 1000.0) == expected


@pytest.mark.parametrize("times", [(1002.0, 1002.0), (1001.0, 1002.0)])
def test_recovered_process_name_rejects_reused_pid(tmp_path, monkeypatch, times):
    from ras_commander import _process_inspection as inspection

    process = SimpleNamespace(
        info={"pid": 90, "name": None, "create_time": 1001.0},
        ppid=lambda: 100,
    )
    monkeypatch.setattr(psutil, "process_iter", lambda _attrs: iter([process]))
    monkeypatch.setattr(inspection, "_WINDOWS_PROCESS_NAMES", True)
    observed_times = iter(times * 2)
    monkeypatch.setattr(inspection, "_windows_process_snapshot_name", lambda pid: "unrelated.exe")
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(pid=pid, create_time=lambda: next(observed_times)))
    assert _query_both(tmp_path) == ((-1,), ((), (-1,)))
