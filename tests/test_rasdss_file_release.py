"""RasDss releases the native DSS file handle before each call returns.

``HecDss.done()`` only drops the Java bridge's file-cache reference; the
native handle can stay open until a background timer closes it a few seconds
later. These tests check that ``RasDss`` releases the file itself, so the
file can be renamed (Windows) or has no open descriptor (Linux) immediately
after a read or write returns, while the JVM is still running.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import textwrap
import types

import pytest

from ras_commander import RasDss


def test_release_dss_file_passes_exact_path_and_force_flag(monkeypatch) -> None:
    calls = []

    class FakeFileAccess:
        @staticmethod
        def close(path, force):
            calls.append((path, force))

    fake_jnius = types.SimpleNamespace(autoclass=lambda name: FakeFileAccess)
    monkeypatch.setitem(sys.modules, "jnius", fake_jnius)

    path = r"C:\Some Folder\Model Data\boundary.dss"
    RasDss._release_dss_file(path)

    assert calls == [(path, True)]


def test_release_dss_file_never_raises(monkeypatch, caplog) -> None:
    class FailingFileAccess:
        @staticmethod
        def close(path, force):
            raise RuntimeError("bridge close failed")

    fake_jnius = types.SimpleNamespace(autoclass=lambda name: FailingFileAccess)
    monkeypatch.setitem(sys.modules, "jnius", fake_jnius)

    with caplog.at_level(logging.DEBUG, logger="ras_commander.dss.RasDss"):
        RasDss._release_dss_file("boundary.dss")

    assert "bridge close failed" in caplog.text
    assert all(record.levelno == logging.DEBUG for record in caplog.records
               if "bridge close failed" in record.getMessage())


@pytest.mark.integration
def test_rasdss_calls_release_file_handle_immediately(tmp_path) -> None:
    script = textwrap.dedent(
        """
        import os
        import sys
        from pathlib import Path

        import numpy as np
        import pandas as pd

        from ras_commander import RasDss

        try:
            RasDss._configure_jvm()
            from jnius import autoclass
            autoclass("hec.heclib.dss.HecDSSFileAccess")
        except Exception as exc:
            print(f"RELEASE_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
            raise SystemExit(77)

        target = Path(sys.argv[1]) / "release-check.dss"
        pathname = "/BASIN/UPSTREAM/FLOW//1HOUR/RELEASE/"
        times = pd.date_range("2020-01-01 00:00", periods=6, freq="h")
        values = np.arange(6, dtype=np.float64) * 10.0

        def open_descriptors(path):
            fd_dir = Path("/proc/self/fd")
            if not fd_dir.is_dir():
                return None
            resolved = str(path.resolve())
            found = []
            for entry in fd_dir.iterdir():
                try:
                    if os.readlink(entry) == resolved:
                        found.append(entry.name)
                except OSError:
                    pass
            return found

        def assert_released(step):
            # Run immediately after the call returns, well inside the bridge's
            # deferred-close delay.
            if os.name == "nt":
                moved = target.with_name(target.name + ".moved")
                try:
                    os.rename(target, moved)
                except OSError as exc:
                    raise AssertionError(
                        f"{step}: DSS file still held after return: {exc}"
                    )
                os.rename(moved, target)
                return
            held = open_descriptors(target)
            if held is None:
                print("RELEASE_PROBE_UNAVAILABLE")
                raise SystemExit(78)
            assert not held, f"{step}: DSS file still open on fds {held}"

        RasDss.write_timeseries(target, pathname, times, values)
        assert_released("write_timeseries (create)")

        df = RasDss.read_timeseries(target, pathname)
        np.testing.assert_array_equal(df["value"].to_numpy(), values)
        assert_released("read_timeseries")

        RasDss.write_timeseries(target, pathname, times, values + 1.0)
        assert_released("write_timeseries (update)")

        catalog = RasDss.get_catalog(target)
        assert len(catalog) >= 1
        assert_released("get_catalog")

        try:
            RasDss.read_timeseries(target, "/NO/SUCH/FLOW//1HOUR/NONE/")
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
        assert_released("read_timeseries (missing pathname)")

        RasDss.get_file_version(target)
        assert_released("get_file_version")

        target = Path(sys.argv[1]) / "release-check-v7.dss"
        RasDss.write_timeseries(target, pathname, times, values, dss_version=7)
        assert_released("write_timeseries (explicit version create)")

        target = Path(sys.argv[1]) / "release-check-grid.dss"
        written = RasDss.write_grid_timeseries(
            dss_file=target,
            pathname="/SHG/TEST/PRECIP/01JAN2020:0000/01JAN2020:0100/RELEASE/",
            data=np.arange(2 * 4 * 4, dtype=np.float32).reshape(2, 4, 4),
            times=[pd.Timestamp("2020-01-01 01:00"), pd.Timestamp("2020-01-01 02:00")],
            grid_info={
                "cellsize": 2000,
                "origin": (1096000, 1516000),
                "crs": "SHG",
                "units": "mm",
                "data_type": "PER-CUM",
            },
        )
        assert_released("write_grid_timeseries")

        grid = RasDss.read_grid(target, written[1])
        assert grid["shape"] == (4, 4)
        assert_released("read_grid")

        print("RELEASE_OK")
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        # This test exercises the Java bridge; do not inherit a native/shadow backend.
        env={k: v for k, v in os.environ.items() if k != "RAS_COMMANDER_DSS_BACKEND"},
    )
    if completed.returncode == 77 and "RELEASE_BRIDGE_UNAVAILABLE:" in completed.stdout:
        pytest.skip(completed.stdout.strip().splitlines()[-1])
    if completed.returncode == 78 and "RELEASE_PROBE_UNAVAILABLE" in completed.stdout:
        pytest.skip("no open-file probe available on this platform")

    diagnostic = (completed.stdout + completed.stderr).casefold()
    assert "access violation" not in diagnostic
    assert completed.returncode == 0, completed.stdout[-3000:] + completed.stderr[-3000:]
    assert "RELEASE_OK" in completed.stdout
