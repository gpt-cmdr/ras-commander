"""RasDss and RasDssGrid against the behaviour of ras-commander-fast-dss 0.1.2.

- ``sync=`` names three flush policies (``"end"``, ``"step"``, ``"none"``; ``True`` and
  ``False`` mean ``"end"`` and ``"none"``). The wrappers pass each one through
  unchanged, the data is stored in every mode, and ``repair`` and ``grid_to_point``
  now take it.
- A ``DssFile`` session that has written keeps one native handle until it is closed.
  RasDss never holds a session on a file it replaces; when a caller's session does,
  the refused replace names the coordination rule and leaves the target unchanged.
- A DSS6 irregular pattern (``IR-`` E part, ``TS-`` D part) is refused by the native
  writer unless the caller opts in. No RasDss writer opts in, so the refusal reaches
  the caller and the new file the write would have created is not left behind.
- The new gridded source flags are reported by ``RasDssGrid.get_features``.

Small files in ``tmp_path`` only. No JVM is started and no HEC model is run. Skips
without an engine that provides the 0.1.2 features.
"""

from __future__ import annotations

import hashlib
import sys

import numpy as np
import pandas as pd
import pytest

dc = pytest.importorskip("ras_commander_fast_dss")

from ras_commander import RasDss, RasDssGrid  # noqa: E402
from ras_commander.dss import _backend, _errors  # noqa: E402

if not _backend.native_feature(_backend.NATIVE_SYNC_MODES_FEATURE):  # pragma: no cover
    pytest.skip("installed ras-commander-fast-dss predates 0.1.2", allow_module_level=True)

TIMES = pd.date_range("2020-01-01 01:00", periods=24, freq="h")
TS_PATH = "/A/B/FLOW//1HOUR/F/"


@pytest.fixture(autouse=True)
def native_backend(monkeypatch):
    monkeypatch.setattr(RasDss, "backend", "native")
    monkeypatch.delenv(_backend.ENV_VAR, raising=False)


def _spy(monkeypatch, module, name):
    real = getattr(module, name)
    calls = []

    def wrapper(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, wrapper)
    return calls


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("sync", ["end", "step", "none", True, False])
@pytest.mark.parametrize("version", [6, 7])
def test_every_sync_mode_reaches_the_engine_and_stores_the_data(
        tmp_path, monkeypatch, sync, version):
    calls = _spy(monkeypatch, dc, "write_timeseries")
    target = tmp_path / "a.dss"
    RasDss.write_timeseries(target, TS_PATH, TIMES, np.arange(24.0), sync=sync,
                            dss_version=version)
    assert calls[0]["sync"] == sync
    assert RasDss.get_file_version(target) == version
    np.testing.assert_array_equal(
        RasDss.read_timeseries(target, TS_PATH)["value"].to_numpy(), np.arange(24.0))


def test_an_unknown_sync_mode_is_refused_by_the_engine_and_leaves_no_file(tmp_path):
    target = tmp_path / "a.dss"
    with pytest.raises((ValueError, TypeError)):
        RasDss.write_timeseries(target, TS_PATH, TIMES, np.arange(24.0), sync="always")
    assert not target.exists()


def test_capabilities_report_the_named_sync_modes():
    attrs = RasDss.get_capabilities().attrs
    assert attrs["native_write_sync_available"] is True
    assert attrs["native_write_sync_modes_available"] is True
    assert tuple(dc.SYNC_MODES) == ("end", "step", "none")


@pytest.mark.parametrize("sync", [None, "end", "step", "none"])
def test_repair_passes_sync_only_when_stated(tmp_path, monkeypatch, sync):
    src = tmp_path / "source.dss"
    RasDss.write_timeseries(src, TS_PATH, TIMES, np.arange(24.0))
    before = _digest(src)
    calls = _spy(monkeypatch, dc, "repair")
    dest = tmp_path / "copy.dss"
    result = RasDss.repair(src, dest, sync=sync)
    if sync is None:
        assert "sync" not in calls[0]
    else:
        assert calls[0]["sync"] == sync
    assert result["complete"] is True
    assert _digest(src) == before
    np.testing.assert_array_equal(
        RasDss.read_timeseries(dest, TS_PATH)["value"].to_numpy(), np.arange(24.0))


def test_repair_with_sync_on_an_engine_without_the_option(tmp_path, monkeypatch):
    src = tmp_path / "source.dss"
    RasDss.write_timeseries(src, TS_PATH, TIMES, np.arange(24.0))

    def old_repair(src, dest):  # the 0.1.1 signature
        raise AssertionError("must not be called")

    monkeypatch.setattr(dc, "repair", old_repair)
    with pytest.raises(_errors.get("DssCapabilityError"), match="sync"):
        RasDss.repair(src, tmp_path / "copy.dss", sync="none")
    assert not (tmp_path / "copy.dss").exists()


def test_grid_to_point_takes_sync_in_0_1_2():
    assert _backend.takes_keyword(dc.gridded.grid_to_point, "sync")


def test_get_features_reports_the_new_gridded_sources():
    features = RasDssGrid.get_features()
    for name in ("gridded_grib1_stage4", "gridded_prism_bil", "gridded_snodas",
                 "gridded_threads_all_cores"):
        assert features[name] is (name in dc.FEATURES)
        assert features[name] is True


def test_dss6_irregular_pattern_is_refused_and_no_file_is_left(tmp_path):
    target = tmp_path / "pattern.dss"
    times = pd.to_datetime(["2000-01-01 00:00", "2000-01-05 06:00", "2000-01-20 12:00"])
    with pytest.raises(_errors.get("DssUnsupportedRecordError"), match="irregular pattern"):
        RasDss.write_timeseries(target, "/A/B/FLOW/TS-PATTERN/IR-MONTH/F/", times,
                                np.array([1.0, 2.0, 3.0]), units="CFS",
                                data_type="INST-VAL", dss_version=6)
    assert not target.exists()


def test_dss6_irregular_series_without_a_pattern_is_still_written(tmp_path):
    target = tmp_path / "irregular.dss"
    times = pd.to_datetime(["2000-01-02 00:00", "2000-01-05 06:00", "2000-01-20 12:00"])
    RasDss.write_timeseries(target, "/A/B/FLOW//IR-MONTH/F/", times,
                            np.array([1.0, 2.0, 3.0]), units="CFS",
                            data_type="INST-VAL", dss_version=6)
    assert RasDss.get_file_version(target) == 6
    frame = RasDss.read_timeseries(target, "/A/B/FLOW//IR-MONTH/F/")
    np.testing.assert_array_equal(frame["value"].to_numpy(), [1.0, 2.0, 3.0])


@pytest.mark.skipif(sys.platform != "win32", reason="the held handle blocks os.replace on Windows")
def test_replace_onto_a_file_a_session_holds_names_the_rule_and_keeps_the_target(tmp_path):
    target = tmp_path / "held.dss"
    RasDss.write_timeseries(target, TS_PATH, TIMES, np.arange(24.0))
    replacement = tmp_path / "replacement.dss"
    RasDss.write_timeseries(replacement, TS_PATH, TIMES, np.arange(24.0) * 2)
    with dc.open(str(target)) as session:
        session.write_timeseries("/A/B/STAGE//1HOUR/F/", np.arange(24.0), times=TIMES,
                                 units="FT", data_type="INST-VAL")
        before = _digest(target)
        with pytest.raises(PermissionError, match="DssFile session"):
            _backend.replace_published(replacement, target)
        assert _digest(target) == before
        assert replacement.exists()
    # Closed: the replace now works.
    _backend.replace_published(replacement, target)
    np.testing.assert_array_equal(
        RasDss.read_timeseries(target, TS_PATH)["value"].to_numpy(), np.arange(24.0) * 2)


def test_replace_published_replaces_when_nothing_holds_the_target(tmp_path):
    target = tmp_path / "t.dss"
    source = tmp_path / "s.dss"
    target.write_bytes(b"old")
    source.write_bytes(b"new")
    _backend.replace_published(source, target)
    assert target.read_bytes() == b"new" and not source.exists()
