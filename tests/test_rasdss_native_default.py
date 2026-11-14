"""The automatic default backend and the parity rules of the native-default audit.

Selection itself (auto, forced overrides, the INFO line, missing or incomplete engines)
is tested in ``test_rasdss_backend.py``. This module covers what changes for callers
when ``auto`` resolves to ``native``, and the ras-commander-side rules found by the
audit (``RC_NATIVE_DEFAULT_PARITY``):

- C1: the Java route refuses an uncompressed DSS6 grid, which HEC Monolith stores with
  an invalid PRECIP_2_BYTE header so that every cell is lost.
- C2: the Java route applies its DSS6 scale/base workaround when it writes into an
  existing DSS6 file without ``dss_version``; before, every cell was lost.
- C8: the native route names the Java backend's swapped DSS6 scale/base convention
  instead of the engine's generic refusal, and never reinterprets the values.
- I8: a DSS6 grid stored with scale 0 reads as a typed ``DssFormatError`` natively
  (Java returns every cell missing).

The Java-side checks run in a worker process (the JVM starts once per process) and
skip without pyjnius, Java and HEC Monolith.
"""

from __future__ import annotations

import os
import pickle
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("ras_commander_fast_dss")

from ras_commander import RasDss  # noqa: E402
from ras_commander.dss import _backend, _errors  # noqa: E402

WORKER = Path(__file__).with_name("_rasdss_native_writes_java_worker.py")
GRID = np.array([[[0.0, 1.5, 2.25, 3.0], [4.0, 5.5, 6.0, 7.25], [0.5, 0.0, 9.0, 10.0]]],
                dtype=np.float32)
BOUNDS = pd.date_range("2020-01-01", periods=2, freq="h")
INFO = {"cellsize": 2000, "origin": (0, 0), "crs": "SHG"}
TIMES = pd.date_range("2020-01-01 01:00", periods=3, freq="h")


class _JavaCalled(Exception):
    pass


@pytest.fixture(autouse=True)
def auto_backend(monkeypatch):
    monkeypatch.delenv(_backend.ENV_VAR, raising=False)
    monkeypatch.setattr(RasDss, "backend", _backend.DEFAULT_BACKEND)
    _backend.reset_default_log()
    yield
    _backend.reset_default_log()


@pytest.fixture
def no_jvm(monkeypatch):
    def _raise():
        raise _JavaCalled("JVM configuration was attempted")

    monkeypatch.setattr(RasDss, "_configure_jvm", staticmethod(_raise))


def _require_ready():
    ready, reason = _backend.native_default_ready()
    if not ready:
        pytest.skip(f"installed engine is not default-ready: {reason}")


def test_auto_reads_and_writes_without_java(no_jvm, tmp_path):
    """With a ready engine the default never starts a JVM, for reads or writes."""
    _require_ready()
    target = tmp_path / "auto.dss"
    RasDss.write_timeseries(target, "/A/B/FLOW//1HOUR/AUTO/", TIMES, np.arange(3.0))
    paths = RasDss.write_grid_timeseries(target, "/SHG/B/PRECIP///AUTO/", GRID, BOUNDS, INFO)
    catalog = RasDss.get_catalog(target)["pathname"].tolist()
    series = [p for p in catalog if p.upper() == "/A/B/FLOW/01JAN2020/1HOUR/AUTO/"]
    assert len(series) == 1, catalog
    frame = RasDss.read_timeseries(target, series[0])
    np.testing.assert_array_equal(frame["value"].to_numpy(), np.arange(3.0))
    np.testing.assert_array_equal(RasDss.read_grid(target, paths[0])["data"], GRID[0])
    assert RasDss.get_file_version(target) == 7
    RasDss.shutdown_jvm()  # a silent no-op under auto


def test_auto_missing_values_are_nan(tmp_path):
    """The behaviour change callers see first: missing values are NaN, not -3.4e38."""
    _require_ready()
    target = tmp_path / "nan.dss"
    RasDss.write_timeseries(target, "/A/B/FLOW//1HOUR/NAN/", TIMES,
                            np.array([1.0, np.nan, 3.0]), dss_version=6)
    frame = RasDss.read_timeseries(target, "/A/B/FLOW/01JAN2020/1HOUR/NAN/")
    assert np.isnan(frame["value"].iloc[1])
    assert not (frame["value"] < -1e30).any()


def test_java_refuses_an_uncompressed_dss6_grid_before_any_file(monkeypatch, no_jvm, tmp_path):
    """C1: Monolith would store a DSS6 grid whose every cell reads as missing."""
    monkeypatch.setattr(RasDss, "backend", "java")
    target = tmp_path / "none6.dss"
    for compression in ("NONE", "undefined"):
        with pytest.raises(_errors.get("DssUnsupportedRecordError"), match="Uncompressed DSS6"):
            RasDss.write_grid_timeseries(target, "/SHG/B/PRECIP///F/", GRID, BOUNDS,
                                         dict(INFO, compression=compression), dss_version=6)
    assert not target.exists()


def test_native_and_java_refuse_an_uncompressed_dss6_grid_alike(monkeypatch, no_jvm, tmp_path):
    for backend in ("java", "native"):
        monkeypatch.setattr(RasDss, "backend", backend)
        with pytest.raises(_errors.get("DssUnsupportedRecordError")):
            RasDss.write_grid_timeseries(tmp_path / f"{backend}.dss", "/SHG/B/PRECIP///F/",
                                         GRID, BOUNDS, dict(INFO, compression="NONE"),
                                         dss_version=6)


def test_native_names_the_java_swapped_dss6_scale_base(no_jvm, tmp_path):
    """C8: Java-era code passed base=100, scale=0 for DSS6; native explains, never swaps."""
    _require_ready()
    target = tmp_path / "swapped6.dss"
    with pytest.raises(ValueError, match="swapped DSS6") as raised:
        RasDss.write_grid_timeseries(
            target, "/SHG/B/PRECIP///F/", GRID, BOUNDS,
            dict(INFO, compression_base=100.0, compression_scale_factor=0.0), dss_version=6)
    message = str(raised.value)
    assert "RasDss.backend = 'java'" in message and _backend.ENV_VAR in message
    assert not target.exists()
    # Named correctly, the same grid is stored and read back exactly.
    paths = RasDss.write_grid_timeseries(
        target, "/SHG/B/PRECIP///F/", GRID, BOUNDS,
        dict(INFO, compression_base=0.0, compression_scale_factor=100.0), dss_version=6)
    np.testing.assert_array_equal(RasDss.read_grid(target, paths[0])["data"], GRID[0])


def _run_java(work: Path, requests):
    req_path, out_path = work / "requests.pkl", work / "results.pkl"
    with open(req_path, "wb") as fh:
        pickle.dump(requests, fh)
    env = {k: v for k, v in os.environ.items() if k != _backend.ENV_VAR}
    proc = subprocess.run(
        [sys.executable, str(WORKER), str(req_path), str(out_path)],
        capture_output=True, text=True, errors="replace", timeout=900, env=env,
    )
    if proc.returncode == 77 or "R1_BRIDGE_UNAVAILABLE" in proc.stdout:
        pytest.skip("Java bridge unavailable: " + proc.stdout.strip()[-300:])
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    with open(out_path, "rb") as fh:
        return pickle.load(fh)


@pytest.fixture(scope="module")
def java_grids(tmp_path_factory):
    work = tmp_path_factory.mktemp("native_default_java")
    existing6 = work / "existing6.dss"
    lossy6 = work / "lossy6.dss"
    requests = [
        # C2: an existing DSS6 file, then a grid written without dss_version.
        {"op": "write_timeseries", "kwargs": dict(
            dss_file=existing6, pathname="/A/B/FLOW//1HOUR/F/", times=TIMES,
            values=np.arange(3.0), dss_version=6)},
        {"op": "write_grid_timeseries", "kwargs": dict(
            dss_file=existing6, pathname="/SHG/B/PRECIP///C2/", data=GRID, times=BOUNDS,
            grid_info=dict(INFO))},
        # I8: scale and base given as named reach Monolith's DSS6 setter swapped (W4),
        # so the record stores scale 0 / base 100 and every cell is lost.
        {"op": "write_grid_timeseries", "kwargs": dict(
            dss_file=lossy6, pathname="/SHG/B/PRECIP///I8/", data=GRID, times=BOUNDS,
            grid_info=dict(INFO, compression_base=0.0, compression_scale_factor=100.0),
            dss_version=6)},
    ]
    results = _run_java(work, requests)
    for result in results:
        assert "error" not in result, result
    c2_path, i8_path = results[1]["result"][0], results[2]["result"][0]
    reads = _run_java(work, [
        {"op": "read_grid", "kwargs": dict(dss_file=existing6, pathname=c2_path)},
        {"op": "read_grid", "kwargs": dict(dss_file=lossy6, pathname=i8_path)},
    ])
    return {"existing6": existing6, "c2": c2_path, "c2_java": reads[0],
            "lossy6": lossy6, "i8": i8_path, "i8_java": reads[1]}


def test_java_grid_into_existing_dss6_file_keeps_every_cell(java_grids):
    """C2: before the fix the Java route stored scale 0 / base 100 and lost every cell."""
    java = java_grids["c2_java"]["result"]
    np.testing.assert_array_equal(java["data"], GRID[0])
    native = RasDss._read_grid_native(java_grids["existing6"], java_grids["c2"])
    np.testing.assert_array_equal(native["data"], GRID[0])
    assert native["metadata"]["compression"]["scale_factor"] > 0


def test_lossy_dss6_grid_is_a_typed_native_error(java_grids):
    """I8: Java returns every cell missing; native refuses with a typed format error."""
    java = java_grids["i8_java"]["result"]
    assert np.isnan(java["data"]).all()
    with pytest.raises(_errors.get("DssFormatError"), match="PRECIP_2_BYTE scale/base"):
        RasDss._read_grid_native(java_grids["lossy6"], java_grids["i8"])
