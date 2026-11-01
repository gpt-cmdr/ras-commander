"""HEC Monolith console messages must never land in DSS files.

HEC Monolith's DSS library prints through a stdout handle that its Fortran runtime caches
at its first message. Redirecting file descriptor 1 (as pytest's capture does around every
test) closes that handle; Windows can reuse its value for the next DSS file the library
opens, and later messages are written into that file. Before ``_silence_hec_messages``,
the loop below read console text back as values from DSS6 files (5 of 30 reads wrong and
11 files holding messages in one run).

The JVM can start only once, so the bridge runs in a subprocess. It skips without Java.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import types

import pytest

from ras_commander import RasDss

WORKER = textwrap.dedent(
    """
    import json, os, sys, tempfile
    from pathlib import Path

    import numpy as np
    import pandas as pd

    os.environ.pop("RAS_COMMANDER_DSS_BACKEND", None)
    from ras_commander import RasDss

    folder, version, result = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
    try:
        RasDss._configure_jvm()
    except Exception as exc:
        print(f"R3_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
        raise SystemExit(77)

    times = pd.date_range("2020-01-01 01:00", periods=48, freq="h")
    values = np.arange(48.0)
    pathname = "//G/FLOW//1HOUR/R/"
    wrong = []
    sink = tempfile.TemporaryFile()
    saved = os.dup(1)
    try:
        for i in range(30):
            os.dup2(sink.fileno(), 1)  # capture on: closes the previous fd-1 handle
            target = folder / f"c{i}.dss"
            RasDss.write_timeseries(target, pathname, times, values, dss_version=version)
            RasDss.write_paired_data(target, "/G/H/STAGE-FLOW///R/", values, values,
                                     x_units="FEET", y_units="CFS")
            back = RasDss.read_timeseries(target, pathname)
            if not np.array_equal(back["value"].to_numpy(), values):
                wrong.append(f"{target.name}:timeseries")
            curve = RasDss.read_paired_data(target, "/G/H/STAGE-FLOW///R/")
            if not np.array_equal(curve.iloc[:, 0].to_numpy(), values):
                wrong.append(f"{target.name}:paired")
            os.dup2(saved, 1)  # capture off
            RasDss.write_timeseries(folder / f"b{i}.dss", "//B/FLOW//1HOUR/R/", times, values,
                                    dss_version=version)
    finally:
        os.dup2(saved, 1)
        os.close(saved)
    # Read while nothing is open: every RasDss call released its file.
    files_with_text = sorted(
        path.name for path in folder.glob("*.dss")
        if b"-----DSS" in path.read_bytes() or b"ZOPEN" in path.read_bytes()
    )
    sink.seek(0)
    result.write_text(json.dumps({
        "silenced": RasDss._messages_silenced,
        "wrong": wrong,
        "files_with_text": files_with_text,
        "captured": sink.read().decode("latin-1"),
    }))
    """
)


@pytest.mark.parametrize("version", [6, 7])
def test_messages_never_land_in_dss_files_when_stdout_is_redirected(tmp_path, version):
    folder = tmp_path / "files"
    folder.mkdir()
    result = tmp_path / "result.json"
    env = {k: v for k, v in os.environ.items() if k != "RAS_COMMANDER_DSS_BACKEND"}
    proc = subprocess.run(
        [sys.executable, "-c", WORKER, str(folder), str(version), str(result)],
        capture_output=True, text=True, errors="replace", timeout=600, env=env,
    )
    if proc.returncode == 77:
        pytest.skip(proc.stdout.strip())
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    report = json.loads(result.read_text())
    assert report["silenced"] is True
    assert report["wrong"] == []
    assert report["files_with_text"] == []
    assert "-----DSS" not in report["captured"]


def _fake_jnius(monkeypatch, calls, fail=False):
    class Heclib:
        @staticmethod
        def Hec_zset(name, text, value):
            if fail:
                raise RuntimeError("no library")
            calls.append((name, text, value))

    module = types.SimpleNamespace(autoclass=lambda name: Heclib)
    monkeypatch.setitem(sys.modules, "jnius", module)
    monkeypatch.setattr(RasDss, "_messages_silenced", False)


def test_message_level_is_set_once_from_the_class_attribute(monkeypatch):
    calls = []
    _fake_jnius(monkeypatch, calls)
    monkeypatch.setattr(RasDss, "hec_message_level", 4)
    RasDss._silence_hec_messages()
    RasDss._silence_hec_messages()
    assert calls == [("MLEVEL", "", 4)]
    assert RasDss.__dict__["hec_message_level"] == 4


def test_message_level_defaults_to_silent():
    assert RasDss.hec_message_level == 0


def test_message_level_failure_never_blocks_dss_io(monkeypatch):
    _fake_jnius(monkeypatch, [], fail=True)
    RasDss._silence_hec_messages()
    assert RasDss._messages_silenced is False


def test_an_already_running_jvm_is_still_silenced(monkeypatch):
    calls = []
    _fake_jnius(monkeypatch, calls)
    config = types.SimpleNamespace(vm_running=True)
    monkeypatch.setitem(sys.modules, "jnius_config", config)
    monkeypatch.setattr(RasDss, "_jvm_configured", False)
    monkeypatch.setattr(RasDss, "_ensure_monolith", staticmethod(lambda: object()))
    RasDss._configure_jvm()
    assert calls == [("MLEVEL", "", 0)]
