"""A prior valid geometry must not complete an active Wine rebuild."""

import importlib
import subprocess
from types import SimpleNamespace

import pytest
from ras_commander import RasProcess

module = importlib.import_module("ras_commander.RasProcess")


@pytest.mark.parametrize(
    "terminal,fresh,completed",
    [
        (False, False, False),
        (False, True, False),
        (True, False, False),
        (True, True, True),
    ],
)
def test_semantic_fallback_requires_terminal_message_and_fresh_file(
    monkeypatch,
    tmp_path,
    terminal,
    fresh,
    completed,
):
    geometry = tmp_path / "model.g01.hdf"
    geometry.write_bytes(b"prior complete tables")
    clock = [0.0]
    process = SimpleNamespace(pid=42, returncode=None, poll=lambda: None)

    def launch(command, **kwargs):
        kwargs["stdout"].write(
            "Completed Writing Geometry\n"
            if terminal
            else "LAYER=Processing 2D Manning's n layer (2/4)\nPROGRESS=0\n"
        )
        kwargs["stdout"].flush()
        if fresh:
            geometry.write_bytes(b"new complete tables, changed size")
        return process

    def cleanup(owned):
        owned.returncode = 15
        owned.poll = lambda: 15
        return {"survivor_pids": []}

    monkeypatch.setattr(module, "IS_LINUX", False)
    monkeypatch.setattr(module.subprocess, "Popen", launch)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    monkeypatch.setattr(
        RasProcess,
        "_geometry_completion_semantics",
        staticmethod(lambda path: {"success": True}),
    )
    monkeypatch.setattr(
        RasProcess, "_terminate_owned_process_tree", staticmethod(cleanup)
    )
    call = lambda: RasProcess._run_complete_geometry_supervised(
        tmp_path / "RasProcess.exe",
        ["CompleteGeometry"],
        geometry,
        timeout=5,
        working_dir=tmp_path,
        semantic_stable_seconds=2,
    )
    if completed:
        result, mode, receipt = call()
        assert mode == "semantic_hdf_stable"
        assert clock[0] >= 2
    else:
        with pytest.raises(subprocess.TimeoutExpired):
            call()
        assert clock[0] >= 5
